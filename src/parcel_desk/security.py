from datetime import datetime, timedelta

import bcrypt
import jwt

ALGORITHM = "HS256"
# 測試中會調低以加速；正式環境維持 bcrypt 預設強度
BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: int, role: str, secret: str, now: datetime, ttl: timedelta) -> str:
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str) -> int:
    """回傳 user id；token 無效或過期時丟出 jwt.InvalidTokenError。"""
    payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    return int(payload["sub"])
