from typing import Annotated

from fastapi import APIRouter, Query, status

from parcel_desk.deps import AdminUser, ClockDep, CurrentUser, DbDep, StaffUser
from parcel_desk.errors import NotFound
from parcel_desk.models import Role
from parcel_desk.schemas.accounts import ResidentOut, UnitCreate, UnitOut
from parcel_desk.schemas.common import UnitCode
from parcel_desk.services import units as unit_service

router = APIRouter(prefix="/units", tags=["戶別"])


@router.post("", response_model=UnitOut, status_code=status.HTTP_201_CREATED, summary="新增戶別")
def create_unit(body: UnitCreate, db: DbDep, clock: ClockDep, _: AdminUser):
    return unit_service.create_unit(db, body.code, clock.now())


@router.get("", response_model=list[UnitOut], summary="戶別列表")
def list_units(
    db: DbDep,
    _: StaffUser,
    building: Annotated[str | None, Query(pattern=r"^[A-Z]$")] = None,
):
    return unit_service.list_units(db, building)


@router.get("/{unit_code}", response_model=UnitOut, summary="查詢單一戶別")
def get_unit(unit_code: UnitCode, db: DbDep, _: StaffUser):
    return unit_service.get_unit(db, unit_code)


@router.delete("/{unit_code}", status_code=status.HTTP_204_NO_CONTENT, summary="刪除戶別")
def delete_unit(unit_code: UnitCode, db: DbDep, _: AdminUser) -> None:
    unit_service.delete_unit(db, unit_code)


@router.get(
    "/{unit_code}/residents",
    response_model=list[ResidentOut],
    summary="該戶住戶（簽收時選擇領取人用）",
)
def list_residents(unit_code: UnitCode, db: DbDep, user: CurrentUser):
    unit = unit_service.get_unit(db, unit_code)
    if user.role == Role.RESIDENT and user.unit_id != unit.id:
        raise NotFound(f"戶號 {unit_code} 不存在", code="UNIT_NOT_FOUND")
    return unit_service.list_residents(db, unit)
