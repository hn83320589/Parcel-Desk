from fastapi import APIRouter, status

from parcel_desk.deps import AdminUser, ClockDep, DbDep
from parcel_desk.models import Role
from parcel_desk.schemas.accounts import UserCreate, UserOut, UserUpdate
from parcel_desk.services import users as user_service

router = APIRouter(prefix="/users", tags=["帳號（管委會）"])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="建立帳號")
def create_user(body: UserCreate, db: DbDep, clock: ClockDep, _: AdminUser):
    return user_service.create_user(db, **body.model_dump(), now=clock.now())


@router.get("", response_model=list[UserOut], summary="帳號列表")
def list_users(db: DbDep, _: AdminUser, role: Role | None = None):
    return user_service.list_users(db, role)


@router.patch("/{user_id}", response_model=UserOut, summary="修改帳號（停用、重設密碼）")
def update_user(user_id: int, body: UserUpdate, db: DbDep, _: AdminUser):
    return user_service.update_user(db, user_id, **body.model_dump(exclude_unset=True))
