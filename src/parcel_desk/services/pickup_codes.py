"""領取碼產生。

- 使用 secrets（密碼學安全亂數）：領取碼等同取件憑證，不可被預測。
- 唯一性的最終保證在資料庫的 partial unique index（只涵蓋 status='pending'），
  這裡先查一次是為了在正常情況下避免撞到 IntegrityError。
"""

import secrets
from collections.abc import Callable

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from parcel_desk.errors import Unavailable
from parcel_desk.models import Package, PackageStatus

CodeGenerator = Callable[[], str]
MAX_ATTEMPTS = 20


def random_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def is_code_active(session: Session, code: str) -> bool:
    stmt = select(
        exists().where(Package.pickup_code == code, Package.status == PackageStatus.PENDING)
    )
    return bool(session.scalar(stmt))


def allocate_code(session: Session, generator: CodeGenerator = random_code) -> str:
    for _ in range(MAX_ATTEMPTS):
        code = generator()
        if not is_code_active(session, code):
            return code
    raise Unavailable("無法產生不重複的領取碼，請稍後再試", code="PICKUP_CODE_EXHAUSTED")
