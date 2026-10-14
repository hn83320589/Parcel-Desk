from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from parcel_desk.deps import AuthenticatedUser, DbDep, JwtSecretDep, SettingsDep
from parcel_desk.schemas.accounts import ChangePasswordRequest, Token, UserOut
from parcel_desk.security import create_access_token
from parcel_desk.services.users import authenticate, change_password

router = APIRouter(prefix="/auth", tags=["認證"])


@router.post("/token", response_model=Token, summary="登入取得 JWT")
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbDep,
    settings: SettingsDep,
    jwt_secret: JwtSecretDep,
) -> Token:
    user = authenticate(db, form.username, form.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="帳號或密碼錯誤",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(
        user.id,
        user.role.value,
        jwt_secret,
        # token 效期是安全機制，固定使用真實時間（PyJWT 驗證 exp 時也是用真實時間）
        datetime.now(UTC),
        timedelta(minutes=settings.jwt_expire_minutes),
    )
    return Token(access_token=token)


@router.get("/me", response_model=UserOut, summary="目前登入者")
def me(user: AuthenticatedUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="修改自己的密碼（首次啟動的 admin 必須先執行）",
)
def update_password(body: ChangePasswordRequest, db: DbDep, user: AuthenticatedUser) -> None:
    change_password(db, user, body.current_password, body.new_password)
