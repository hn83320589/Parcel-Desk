"""登入失敗次數限制（記憶體內計數）。

以「帳號 + 來源 IP」為單位：連續失敗 max_failures 次後鎖定 lockout，期間即使密碼正確也拒絕；
成功登入會清除計數。只存在單一 API 程序的記憶體中，重啟後歸零（本系統只跑單一程序）。
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

Key = tuple[str, str]  # (username, client_ip)


@dataclass
class _Entry:
    failures: int = 0
    locked_until: datetime | None = None


class LoginThrottle:
    def __init__(
        self,
        max_failures: int = 5,
        lockout: timedelta = timedelta(minutes=5),
        max_entries: int = 10_000,
    ) -> None:
        self.max_failures = max_failures
        self.lockout = lockout
        self.max_entries = max_entries
        self._entries: dict[Key, _Entry] = {}  # 依最後失敗時間排序（舊 → 新）
        self._lock = threading.Lock()  # 同步端點在 threadpool 中並行執行

    def locked_for(self, key: Key, now: datetime) -> timedelta | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry.locked_until and now < entry.locked_until:
                return entry.locked_until - now
            return None

    def record_failure(self, key: Key, now: datetime) -> None:
        with self._lock:
            entry = self._entries.pop(key, None) or _Entry()
            if entry.locked_until and now >= entry.locked_until:
                entry = _Entry()  # 鎖定已過期，重新計算
            entry.failures += 1
            if entry.failures >= self.max_failures:
                entry.failures = 0
                entry.locked_until = now + self.lockout
            self._entries[key] = entry
            # 防止大量不同帳號名稱把記憶體撐爆：淘汰最久沒有失敗紀錄的項目
            while len(self._entries) > self.max_entries:
                self._entries.pop(next(iter(self._entries)))

    def reset(self, key: Key) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def __len__(self) -> int:
        return len(self._entries)
