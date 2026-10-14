from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from parcel_desk.clock import local_datetime
from parcel_desk.errors import Conflict, NotFound
from parcel_desk.models import Package, PackageStatus, PackageType, Role, User
from parcel_desk.services.notifications import notify_arrival
from parcel_desk.services.pickup_codes import CodeGenerator, allocate_code, random_code
from parcel_desk.services.units import get_unit, get_unit_for_input

# 兩個櫃台同時登記、恰好抽到同一組碼時，資料庫唯一索引會擋下，整筆交易重做
MAX_INSERT_ATTEMPTS = 3

STATUS_LABELS = {
    PackageStatus.PICKED_UP: "已簽收",
    PackageStatus.RETURNED: "已退回物流",
    PackageStatus.LOST: "已標記遺失",
}


def register_package(
    session: Session,
    *,
    unit_code: str,
    carrier: str,
    type: PackageType,
    staff: User,
    now: datetime,
    recipient_name: str | None = None,
    tracking_no: str | None = None,
    code_generator: CodeGenerator = random_code,
) -> Package:
    unit_id = get_unit_for_input(session, unit_code).id
    for _ in range(MAX_INSERT_ATTEMPTS):
        package = Package(
            unit_id=unit_id,
            recipient_name=recipient_name,
            carrier=carrier,
            tracking_no=tracking_no,
            type=type,
            status=PackageStatus.PENDING,
            pickup_code=allocate_code(session, code_generator),
            registered_at=now,
            registered_by=staff.id,
        )
        session.add(package)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            if "pickup_code" not in str(exc.orig):
                raise
            continue
        notify_arrival(session, package, now)
        session.commit()
        return package
    raise Conflict("領取碼衝突，請重新登記", code="PICKUP_CODE_CONFLICT")


@dataclass
class PackageFilter:
    unit_code: str | None = None
    status: PackageStatus | None = None
    date_from: date | None = None  # 台北時間，含當日
    date_to: date | None = None  # 台北時間，含當日
    needs_attention: bool | None = None


def list_packages(
    session: Session, filters: PackageFilter, viewer: User, limit: int, offset: int
) -> tuple[list[Package], int]:
    conditions = []
    if viewer.role == Role.RESIDENT:
        conditions.append(Package.unit_id == viewer.unit_id)
    if filters.unit_code:
        conditions.append(Package.unit_id == get_unit(session, filters.unit_code).id)
    if filters.status:
        conditions.append(Package.status == filters.status)
    if filters.date_from:
        conditions.append(Package.registered_at >= local_datetime(filters.date_from))
    if filters.date_to:
        end = local_datetime(filters.date_to + timedelta(days=1))
        conditions.append(Package.registered_at < end)
    if filters.needs_attention is not None:
        flag = Package.needs_attention_at.is_not(None)
        conditions.append(flag if filters.needs_attention else ~flag)

    total = session.scalar(select(func.count()).select_from(Package).where(*conditions))
    stmt = (
        select(Package)
        .join(Package.unit)
        .where(*conditions)
        .order_by(Package.registered_at.desc(), Package.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt).unique()), total or 0


def get_package(session: Session, package_id: int, viewer: User) -> Package:
    package = session.get(Package, package_id)
    # 住戶查他戶包裹回 404：不透露該 id 的包裹是否存在
    if package is None or (viewer.role == Role.RESIDENT and package.unit_id != viewer.unit_id):
        raise NotFound("包裹不存在", code="PACKAGE_NOT_FOUND")
    return package


def find_pending_by_code(session: Session, code: str) -> Package:
    package = session.scalar(
        select(Package).where(Package.pickup_code == code, Package.status == PackageStatus.PENDING)
    )
    if package is not None:
        return package
    latest = session.scalar(
        select(Package).where(Package.pickup_code == code).order_by(Package.id.desc()).limit(1)
    )
    if latest is not None:
        raise Conflict(
            f"領取碼已失效（包裹{STATUS_LABELS[latest.status]}）", code="PICKUP_CODE_INACTIVE"
        )
    raise NotFound("查無此領取碼", code="PICKUP_CODE_NOT_FOUND")


def ensure_pending(package: Package) -> None:
    if package.status != PackageStatus.PENDING:
        raise Conflict(f"包裹{STATUS_LABELS[package.status]}，無法再處理", code="PACKAGE_CLOSED")


def mark_exception(
    session: Session,
    package_id: int,
    *,
    status: PackageStatus,
    reason: str,
    staff: User,
    now: datetime,
) -> Package:
    if status not in (PackageStatus.RETURNED, PackageStatus.LOST):
        raise ValueError(f"不支援的異常狀態：{status}")
    package = get_package(session, package_id, staff)
    ensure_pending(package)
    # 條件式更新：與簽收同時發生時，只有一方會成功
    result = session.execute(
        update(Package)
        .where(Package.id == package.id, Package.status == PackageStatus.PENDING)
        .values(status=status, exception_reason=reason, exception_at=now, exception_by=staff.id)
    )
    if result.rowcount == 0:
        session.rollback()
        session.refresh(package)
        ensure_pending(package)
    session.commit()
    session.refresh(package)
    return package
