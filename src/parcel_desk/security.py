import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path

import bcrypt
import jwt

ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32
# 曾經公開在 repo 中的預設值：任何人都能用它偽造 token，一律拒絕
KNOWN_INSECURE_SECRETS = frozenset({"dev-secret-change-me-in-production"})
# 測試中會調低以加速；正式環境維持 bcrypt 預設強度
BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(
    user_id: int, role: str, secret: str, now: datetime, ttl: timedelta, audience: str
) -> str:
    """audience 為資料庫的安裝識別碼：token 只在簽發它的那個資料庫有效。"""
    payload = {"sub": str(user_id), "role": role, "aud": audience, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str, audience: str) -> int:
    """回傳 user id；token 無效、過期或 aud 不符（含沒有 aud）時丟出 jwt.InvalidTokenError。"""
    payload = jwt.decode(
        token, secret, algorithms=[ALGORITHM], audience=audience, options={"require": ["aud"]}
    )
    return int(payload["sub"])


class InsecureSecretError(RuntimeError):
    pass


def resolve_jwt_secret(configured: str | None, secret_file: Path) -> str:
    """取得 JWT 密鑰。

    - 有設定 PARCEL_JWT_SECRET：檢查長度與黑名單後使用。
    - 沒有設定：首次啟動時隨機產生並存到 secret_file（權限 600），之後沿用，
      讓重啟後既有的登入不會失效；每一套安裝的密鑰都不同。
    """
    if configured is not None:
        return _validated(configured, "PARCEL_JWT_SECRET")
    if secret_file.exists():
        return _validated(secret_file.read_text().strip(), str(secret_file))

    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    try:
        # O_EXCL：兩個程序同時首次啟動時，只有一方能建立檔案
        fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # 另一個程序搶先建立了，改用它的密鑰
        return _validated(secret_file.read_text().strip(), str(secret_file))
    with os.fdopen(fd, "w") as f:
        f.write(secret)
    return secret


def _validated(secret: str, source: str) -> str:
    if secret in KNOWN_INSECURE_SECRETS:
        raise InsecureSecretError(f"{source} 使用了公開的預設值，請改成隨機字串")
    if len(secret) < MIN_SECRET_LENGTH:
        raise InsecureSecretError(f"{source} 的密鑰至少需要 {MIN_SECRET_LENGTH} 個字元")
    return secret
