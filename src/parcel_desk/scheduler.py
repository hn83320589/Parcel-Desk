"""APScheduler 內嵌於 API 程序：每 N 分鐘執行一次 run_reminders。

為什麼不是「每天 09:00 跑一次」：冷藏的 24 / 48 小時不是固定時點，需要較密集檢查；
一般包裹的 09:00 由 run_reminders 自己判斷，因此 09:00 後第一次執行就會送出，
同一天之後的執行不會重複。電腦晚開機時，第一次執行即會補送。
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session, sessionmaker

from parcel_desk.clock import LOCAL_TZ, Clock
from parcel_desk.services.reminders import run_reminders

logger = logging.getLogger(__name__)

JOB_ID = "reminders"


def run_reminders_job(session_factory: sessionmaker[Session], clock: Clock) -> None:
    with session_factory() as session:
        result = run_reminders(session, clock.now())
    logger.info(
        "逾期提醒完成：一般/大型 %d 件、冷藏 %d 件、需處理 %d 件",
        result.overdue,
        result.cold,
        result.needs_attention,
    )


def start_scheduler(
    session_factory: sessionmaker[Session], clock: Clock, interval_minutes: int
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=LOCAL_TZ)
    scheduler.add_job(
        run_reminders_job,
        "interval",
        minutes=interval_minutes,
        args=[session_factory, clock],
        id=JOB_ID,
        next_run_time=datetime.now(LOCAL_TZ),  # 啟動時立即執行一次，補送停機期間的提醒
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler
