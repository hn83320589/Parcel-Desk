"""通知紀錄。通知不實際發送，只寫入資料表並提供 API 查詢。

到件通知合併規則（固定視窗）：
同一戶第一件包裹登記時開啟一則通知，視窗為 10 分鐘；視窗內登記的包裹併入同一則。
不採滑動視窗，否則包裹持續進來時視窗會一直延長，住戶遲遲收不到通知。
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from parcel_desk.errors import NotFound
from parcel_desk.models import (
    Notification,
    NotificationKind,
    Package,
    PackageType,
    Role,
    Unit,
    User,
)
from parcel_desk.services.units import list_residents

MERGE_WINDOW = timedelta(minutes=10)

TYPE_LABELS = {PackageType.NORMAL: "一般", PackageType.LARGE: "大型", PackageType.COLD: "冷藏"}


def describe_package(package: Package) -> str:
    return f"{package.carrier}（{TYPE_LABELS[package.type]}）領取碼 {package.pickup_code}"


def _package_lines(packages: Iterable[Package]) -> str:
    return "\n".join(f"{i}. {describe_package(p)}" for i, p in enumerate(packages, start=1))


def notify_arrival(session: Session, package: Package, now: datetime) -> Notification:
    """呼叫端負責 commit，讓包裹與通知在同一個交易內完成。

    併發前提（換資料庫時必須重新處理）：「查詢開啟中的視窗 → 沒有就新建」本身不是原子操作。
    目前的正確性來自 SQLite 的單一寫入鎖：呼叫端在這之前已 flush 包裹（INSERT），
    取得了資料庫的寫入鎖，另一個櫃台的登記必須等這個交易 commit 才能寫入，
    因此它查詢視窗時一定看得到這裡建立的通知（見 test_concurrent_registrations_...）。
    換成 PostgreSQL 等列級鎖資料庫時會變成競態，需要改用 SELECT ... FOR UPDATE 鎖住戶別列，
    或以 (unit_id, 視窗) 唯一約束加上衝突重試。
    """
    notification = session.scalar(
        select(Notification)
        .where(
            Notification.kind == NotificationKind.ARRIVAL,
            Notification.unit_id == package.unit_id,
            Notification.created_at <= now,
            Notification.window_ends_at > now,
        )
        .order_by(Notification.id.desc())
        .limit(1)
    )
    unit = session.get(Unit, package.unit_id)
    if notification is None:
        notification = Notification(
            kind=NotificationKind.ARRIVAL,
            unit_id=unit.id,
            created_at=now,
            window_ends_at=now + MERGE_WINDOW,
            recipients=list_residents(session, unit),
        )
        session.add(notification)
    notification.packages.append(package)
    count = len(notification.packages)
    notification.title = f"包裹到件通知（{count} 件）"
    notification.body = (
        f"{unit.code} 您好，管理室代收了 {count} 件包裹，請攜帶領取碼至大廳櫃台領取：\n"
        + _package_lines(notification.packages)
    )
    return notification


def create_notification(
    session: Session,
    *,
    kind: NotificationKind,
    unit: Unit,
    title: str,
    packages: list[Package],
    recipients: list[User],
    now: datetime,
    intro: str,
) -> Notification:
    notification = Notification(
        kind=kind,
        unit_id=unit.id,
        title=title,
        body=f"{intro}\n{_package_lines(packages)}",
        created_at=now,
        packages=packages,
        recipients=recipients,
    )
    session.add(notification)
    return notification


# 住戶只能看到自家戶別、且以住戶為對象的通知（「需處理」是給管委會的）
RESIDENT_VISIBLE_KINDS = (
    NotificationKind.ARRIVAL,
    NotificationKind.OVERDUE_REMINDER,
    NotificationKind.COLD_REMINDER,
)


def _visibility(viewer: User):
    if viewer.role == Role.RESIDENT:
        return [
            Notification.unit_id == viewer.unit_id,
            Notification.kind.in_(RESIDENT_VISIBLE_KINDS),
        ]
    return []


def list_notifications(
    session: Session,
    viewer: User,
    *,
    unit: Unit | None = None,
    kind: NotificationKind | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    conditions = _visibility(viewer)
    if unit is not None:
        conditions.append(Notification.unit_id == unit.id)
    if kind is not None:
        conditions.append(Notification.kind == kind)
    stmt = (
        select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt))


def get_notification(session: Session, notification_id: int, viewer: User) -> Notification:
    notification = session.scalar(
        select(Notification).where(Notification.id == notification_id, *_visibility(viewer))
    )
    if notification is None:
        raise NotFound("通知不存在", code="NOTIFICATION_NOT_FOUND")
    return notification
