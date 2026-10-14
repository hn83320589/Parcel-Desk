from collections.abc import Iterator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from parcel_desk.clock import Clock
from parcel_desk.config import Settings
from parcel_desk.errors import Forbidden
from parcel_desk.models import Role, User
from parcel_desk.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_jwt_secret(request: Request) -> str:
    return request.app.state.jwt_secret


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
ClockDep = Annotated[Clock, Depends(get_clock)]
DbDep = Annotated[Session, Depends(get_db)]
JwtSecretDep = Annotated[str, Depends(get_jwt_secret)]


def get_authenticated_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: DbDep, jwt_secret: JwtSecretDep
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登入資訊無效或已過期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token, jwt_secret)
    except jwt.InvalidTokenError as exc:
        raise unauthorized from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


# 只驗證身分；給「目前登入者」與「修改密碼」使用
AuthenticatedUser = Annotated[User, Depends(get_authenticated_user)]


def get_current_user(user: AuthenticatedUser) -> User:
    """其他所有 API：使用一次性密碼登入的帳號，必須先修改密碼。"""
    if user.must_change_password:
        raise Forbidden(
            "請先修改密碼（POST /auth/change-password）", code="PASSWORD_CHANGE_REQUIRED"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="權限不足")
        return user

    return checker


# 管委會也在現場作業，因此擁有管理員的所有權限
StaffUser = Annotated[User, Depends(require_roles(Role.ADMIN, Role.STAFF))]
AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
