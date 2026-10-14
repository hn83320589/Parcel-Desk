from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from parcel_desk.deps import AdminUser, ClockDep, DbDep
from parcel_desk.services.reports import MonthlyReport, monthly_report, to_csv

router = APIRouter(prefix="/reports", tags=["月報（管委會）"])

MonthQuery = Annotated[
    str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="例如 2026-10", examples=["2026-10"])
]


class ReportRowOut(BaseModel):
    unit_code: str
    received: int
    picked_up: int
    avg_pickup_hours: float | None
    overdue: int
    cold_needs_attention: int


class MonthlyReportOut(BaseModel):
    month: str
    rows: list[ReportRowOut]
    total: ReportRowOut


def _build(db, clock, month: str) -> MonthlyReport:
    year, mon = (int(part) for part in month.split("-"))
    return monthly_report(db, year, mon, clock.now())


@router.get("/monthly", response_model=MonthlyReportOut, summary="月報")
def get_monthly(month: MonthQuery, db: DbDep, clock: ClockDep, _: AdminUser):
    return MonthlyReportOut.model_validate(_build(db, clock, month), from_attributes=True)


@router.get(
    "/monthly.csv",
    summary="月報 CSV 匯出（UTF-8 BOM，Excel 可直接開啟）",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_monthly_csv(month: MonthQuery, db: DbDep, clock: ClockDep, _: AdminUser) -> Response:
    report = _build(db, clock, month)
    return Response(
        content=to_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="parcel-report-{report.month}.csv"'},
    )
