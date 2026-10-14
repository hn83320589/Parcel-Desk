from dataclasses import asdict

from fastapi import APIRouter

from parcel_desk.deps import AdminUser, ClockDep, DbDep
from parcel_desk.services.reminders import run_reminders

router = APIRouter(prefix="/admin", tags=["管理"])


@router.post("/run-reminders", summary="立即執行一次逾期提醒（排程也會自動執行）")
def trigger_reminders(db: DbDep, clock: ClockDep, _: AdminUser) -> dict[str, int]:
    return asdict(run_reminders(db, clock.now()))
