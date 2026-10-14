import secrets
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from parcel_desk.errors import Conflict, InvalidField, NotFound
from parcel_desk.models import Role, User
from parcel_desk.security import hash_password, verify_password
from parcel_desk.services.units import get_unit_for_input


def create_user(
    session: Session,
    *,
    username: str,
    password: str,
    display_name: str,
    role: Role,
    unit_code: str | None,
    now: datetime,
) -> User:
    if role == Role.RESIDENT and unit_code is None:
        raise InvalidField("unit_code", "住戶帳號必須指定戶號")
    if role != Role.RESIDENT and unit_code is not None:
        raise InvalidField("unit_code", "只有住戶帳號可以指定戶號")
    if session.scalar(select(exists().where(User.username == username))):
        raise Conflict(f"帳號 {username} 已存在", code="USERNAME_EXISTS")

    unit = get_unit_for_input(session, unit_code) if unit_code else None
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
        unit=unit,
        is_active=True,
        created_at=now,
    )
    session.add(user)
    session.commit()
    return user


def list_users(session: Session, role: Role | None = None) -> list[User]:
    stmt = select(User).order_by(User.id)
    if role:
        stmt = stmt.where(User.role == role)
    return list(session.scalars(stmt))


def update_user(
    session: Session,
    user_id: int,
    *,
    display_name: str | None = None,
    password: str | None = None,
    is_active: bool | None = None,
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise NotFound("使用者不存在")
    if display_name is not None:
        user.display_name = display_name
    if password is not None:
        user.password_hash = hash_password(password)
    if is_active is not None:
        user.is_active = is_active
    session.commit()
    return user


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


BOOTSTRAP_ADMIN_USERNAME = "admin"


def bootstrap_admin(session: Session, now: datetime) -> str | None:
    """正式模式首次啟動（資料庫沒有任何帳號）時建立管委會帳號。

    回傳一次性隨機密碼供呼叫端顯示；帳號被標記為必須先修改密碼。已有帳號時回傳 None。
    """
    if session.scalar(select(exists().where(User.id.is_not(None)))):
        return None
    password = secrets.token_urlsafe(12)
    admin = create_user(
        session,
        username=BOOTSTRAP_ADMIN_USERNAME,
        password=password,
        display_name="管委會",
        role=Role.ADMIN,
        unit_code=None,
        now=now,
    )
    admin.must_change_password = True
    session.commit()
    return password


def change_password(session: Session, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise InvalidField("current_password", "目前密碼錯誤")
    if current == new:
        raise InvalidField("new_password", "新密碼不可與目前密碼相同")
    user.password_hash = hash_password(new)
    user.must_change_password = False
    session.commit()
