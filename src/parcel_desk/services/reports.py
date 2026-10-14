"""月報。

- 月份歸屬：以包裹登記時間（台北時間）所在月份計。
- 平均領取時間：該月登記且已簽收者 (簽收時間 − 登記時間) 的平均，單位小時，四捨五入至小數 2 位。
- 逾期件數：以時間戳判斷，不依賴排程是否有執行。
  一般/大型：簽收（或結案、或尚未領取則以現在）時已超過「登記日 + 7 天 09:00」，與提醒規則一致；
  冷藏：超過 24 小時。
- 冷藏需處理件數：曾被標示「需處理」者。
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from parcel_desk.clock import local_date, local_datetime
from parcel_desk.models import Package, PackageStatus, PackageType
from parcel_desk.services.reminders import COLD_REMIND_AFTER, DAILY_REMIND_TIME, OVERDUE_DAYS

TOTAL_LABEL = "合計"
CSV_HEADER = ["戶號", "收件數", "已領件數", "平均領取時間（小時）", "逾期件數", "冷藏需處理件數"]


@dataclass
class ReportRow:
    unit_code: str
    received: int = 0
    picked_up: int = 0
    avg_pickup_hours: float | None = None
    overdue: int = 0
    cold_needs_attention: int = 0
    _pickup_seconds: list[float] = field(default_factory=list, repr=False)

    def add(self, package: Package, now: datetime) -> None:
        self.received += 1
        if package.status == PackageStatus.PICKED_UP:
            self.picked_up += 1
            duration = package.pickup.picked_up_at - package.registered_at
            self._pickup_seconds.append(duration.total_seconds())
        if is_overdue(package, now):
            self.overdue += 1
        if package.needs_attention_at is not None:
            self.cold_needs_attention += 1

    def finalize(self) -> "ReportRow":
        if self._pickup_seconds:
            avg = sum(self._pickup_seconds) / len(self._pickup_seconds) / 3600
            self.avg_pickup_hours = round(avg, 2)
        return self


@dataclass
class MonthlyReport:
    month: str
    rows: list[ReportRow]
    total: ReportRow


def _closed_at(package: Package, now: datetime) -> datetime:
    if package.pickup is not None:
        return package.pickup.picked_up_at
    return package.exception_at or now


def is_overdue(package: Package, now: datetime) -> bool:
    closed_at = _closed_at(package, now)
    if package.type == PackageType.COLD:
        return closed_at - package.registered_at >= COLD_REMIND_AFTER
    first_reminder = local_datetime(
        local_date(package.registered_at) + timedelta(days=OVERDUE_DAYS), DAILY_REMIND_TIME
    )
    return closed_at >= first_reminder


def monthly_report(session: Session, year: int, month: int, now: datetime) -> MonthlyReport:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    packages = session.scalars(
        select(Package).where(
            Package.registered_at >= local_datetime(start),
            Package.registered_at < local_datetime(end),
        )
    ).unique()

    rows: dict[str, ReportRow] = {}
    sort_keys: dict[str, tuple] = {}
    total = ReportRow(unit_code=TOTAL_LABEL)
    for package in packages:
        code = package.unit.code
        if code not in rows:
            rows[code] = ReportRow(unit_code=code)
            sort_keys[code] = (package.unit.building, package.unit.floor, package.unit.number)
        rows[code].add(package, now)
        total.add(package, now)

    ordered = [rows[code].finalize() for code in sorted(rows, key=sort_keys.__getitem__)]
    return MonthlyReport(month=f"{year:04d}-{month:02d}", rows=ordered, total=total.finalize())


def to_csv(report: MonthlyReport) -> bytes:
    """UTF-8 with BOM + CRLF：Excel 直接開啟中文不會亂碼。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for row in [*report.rows, report.total]:
        writer.writerow(
            [
                row.unit_code,
                row.received,
                row.picked_up,
                "" if row.avg_pickup_hours is None else f"{row.avg_pickup_hours:.2f}",
                row.overdue,
                row.cold_needs_attention,
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")
