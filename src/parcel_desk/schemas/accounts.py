from pydantic import BaseModel, Field

from parcel_desk.models import Role
from parcel_desk.schemas.common import LocalDateTime, ORMModel, UnitCode


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UnitCreate(BaseModel):
    code: UnitCode = Field(examples=["A-12F-3"])


class UnitOut(ORMModel):
    id: int
    code: str
    building: str
    floor: int
    number: int


class UserCreate(BaseModel):
    # bcrypt 只處理前 72 bytes，超過的部分會被忽略，因此直接限制長度
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(min_length=1, max_length=50)
    role: Role
    unit_code: UnitCode | None = Field(default=None, description="住戶必填，其他角色不可填")


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    password: str | None = Field(default=None, min_length=8, max_length=72)
    is_active: bool | None = None


class UserOut(ORMModel):
    id: int
    username: str
    display_name: str
    role: Role
    unit_code: str | None
    is_active: bool
    created_at: LocalDateTime


class ResidentOut(ORMModel):
    id: int
    display_name: str
