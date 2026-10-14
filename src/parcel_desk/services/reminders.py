"""逾期提醒。run_reminders 是冪等的：重複執行、或停機後補跑都不會重複提醒。

- 一般 / 大型：台北時間 09:00 之後，登記日起算滿 7 個日曆日仍未領取者，每天提醒一次。
  例：10/1（任何時間）登記 → 10/8 09:00 起每天提醒。
- 冷藏：登記滿 24 小時提醒一次；滿 48 小時標示「需處理」並通知管委會。
  冷藏不套用 7 天的每日提醒。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from parcel_desk.clock import local_date, local_datetime, to_local
from parcel_desk.models import (
    NotificationKind,
    Package,
    PackageReminder,
    PackageStatus,
    PackageType,
    ReminderKind,
    Role,
    Unit,
    User,
)
from parcel_desk.services.notifications import create_notification
from parcel_desk.services.units import list_residents

DAILY_REMIND_TIME = time(9, 0)
OVERDUE_DAYS = 7
COLD_REMIND_AFTER = timedelta(hours=24)
COLD_ATTENTION_AFTER = timedelta(hours=48)


@dataclass
class ReminderResult:
    """本次執行處理的包裹件數。"""

    overdue: int = 0
    cold: int = 0
    needs_attention: int = 0


def run_reminders(session: Session, now: datetime) -> ReminderResult:
    today = local_date(now)
    result = ReminderResult()
    if to_local(now).time() >= DAILY_REMIND_TIME:
        result.overdue = _daily_overdue(session, now, today)
    result.cold = _cold_reminder(session, now, today)
    result.needs_attention = _cold_needs_attention(session, now, today)
    session.commit()
    return result


def _not_reminded(kind: ReminderKind, on: date | None = None):
    stmt = select(PackageReminder.package_id).where(PackageReminder.kind == kind)
    if on is not None:
        stmt = stmt.where(PackageReminder.remind_date == on)
    return Package.id.not_in(stmt)


def _pending(*conditions) -> list:
    return [Package.status == PackageStatus.PENDING, *conditions]


def _daily_overdue(session: Session, now: datetime, today: date) -> int:
    # 登記日 <= 今天 - 7 天  ⇔  登記時間早於「今天 - 6 天」的 00:00（台北）
    cutoff = local_datetime(today - timedelta(days=OVERDUE_DAYS - 1))
    packages = session.scalars(
        select(Package).where(
            *_pending(
                Package.type.in_((PackageType.NORMAL, PackageType.LARGE)),
                Package.registered_at < cutoff,
                _not_reminded(ReminderKind.OVERDUE_DAILY, on=today),
            )
        )
    ).unique()
    return _notify_by_unit(
        session,
        list(packages),
        reminder_kind=ReminderKind.OVERDUE_DAILY,
        notification_kind=NotificationKind.OVERDUE_REMINDER,
        title=lambda unit, n: f"逾期未領提醒（{n} 件）",
        intro=lambda unit: (
            f"{unit.code} 您好，以下包裹已超過 {OVERDUE_DAYS} 天未領取，請儘速至管理室領取："
        ),
        recipients=lambda unit: list_residents(session, unit),
        now=now,
        today=today,
    )


def _cold_reminder(session: Session, now: datetime, today: date) -> int:
    packages = session.scalars(
        select(Package).where(
            *_pending(
                Package.type == PackageType.COLD,
                Package.registered_at <= now - COLD_REMIND_AFTER,
                _not_reminded(ReminderKind.COLD_24H),
            )
        )
    ).unique()
    return _notify_by_unit(
        session,
        list(packages),
        reminder_kind=ReminderKind.COLD_24H,
        notification_kind=NotificationKind.COLD_REMINDER,
        title=lambda unit, n: f"冷藏包裹提醒（{n} 件）",
        intro=lambda unit: (
            f"{unit.code} 您好，以下冷藏包裹已超過 24 小時未領取，請儘速領取以免變質："
        ),
        recipients=lambda unit: list_residents(session, unit),
        now=now,
        today=today,
    )


def _cold_needs_attention(session: Session, now: datetime, today: date) -> int:
    packages = list(
        session.scalars(
            select(Package).where(
                *_pending(
                    Package.type == PackageType.COLD,
                    Package.registered_at <= now - COLD_ATTENTION_AFTER,
                    Package.needs_attention_at.is_(None),
                )
            )
        ).unique()
    )
    for package in packages:
        package.needs_attention_at = now
    admins = list(
        session.scalars(select(User).where(User.role == Role.ADMIN, User.is_active.is_(True)))
    )
    return _notify_by_unit(
        session,
        packages,
        reminder_kind=ReminderKind.COLD_48H,
        notification_kind=NotificationKind.NEEDS_ATTENTION,
        title=lambda unit, n: f"冷藏包裹需處理（{unit.code}，{n} 件）",
        intro=lambda unit: f"{unit.code} 的以下冷藏包裹已超過 48 小時未領取，請管委會協助處理：",
        recipients=lambda unit: admins,
        now=now,
        today=today,
    )


def _notify_by_unit(
    session: Session,
    packages: list[Package],
    *,
    reminder_kind: ReminderKind,
    notification_kind: NotificationKind,
    title,
    intro,
    recipients,
    now: datetime,
    today: date,
) -> int:
    """同一戶的多件包裹合併成一則通知，並為每件包裹寫入提醒紀錄。"""
    by_unit: dict[int, list[Package]] = defaultdict(list)
    for package in packages:
        by_unit[package.unit_id].append(package)

    for unit_id, unit_packages in by_unit.items():
        unit = session.get(Unit, unit_id)
        notification = create_notification(
            session,
            kind=notification_kind,
            unit=unit,
            title=title(unit, len(unit_packages)),
            intro=intro(unit),
            packages=unit_packages,
            recipients=recipients(unit),
            now=now,
        )
        session.flush()
        for package in unit_packages:
            session.add(
                PackageReminder(
                    package_id=package.id,
                    kind=reminder_kind,
                    remind_date=today,
                    notification_id=notification.id,
                    created_at=now,
                )
            )
    return len(packages)
