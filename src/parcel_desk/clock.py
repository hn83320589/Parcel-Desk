"""時間來源與時區換算。

資料庫一律存 UTC；商業規則中的「09:00」「哪一天」「哪個月」一律以台北時間判斷。
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Taipei")


class Clock(Protocol):
    def now(self) -> datetime:
        """回傳 aware 的 UTC 時間。"""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """測試與 seed 用的可控時鐘。"""

    def __init__(self, now: datetime) -> None:
        self.set(now)

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FixedClock 需要 aware datetime")
        self._now = now.astimezone(UTC)

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)


def to_local(dt: datetime) -> datetime:
    return dt.astimezone(LOCAL_TZ)


def local_date(dt: datetime) -> date:
    return to_local(dt).date()


def local_datetime(d: date, t: time = time(0, 0)) -> datetime:
    """台北時間的某日某時，轉成 UTC。"""
    return datetime.combine(d, t, tzinfo=LOCAL_TZ).astimezone(UTC)


def ensure_aware(dt: datetime) -> datetime:
    """沒有時區的輸入視為台北時間。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ).astimezone(UTC)
    return dt.astimezone(UTC)
