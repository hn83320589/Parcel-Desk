from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from parcel_desk.deps import ClockDep, CurrentUser, DbDep, StaffUser
from parcel_desk.models import PackageStatus
from parcel_desk.schemas.common import Page, UnitCode
from parcel_desk.schemas.packages import (
    ExceptionRequest,
    PackageCreate,
    PackageOut,
    PickupByCodeRequest,
    PickupRequest,
)
from parcel_desk.services import packages as package_service
from parcel_desk.services import pickups as pickup_service

router = APIRouter(tags=["包裹"])


@router.post(
    "/packages",
    response_model=PackageOut,
    status_code=status.HTTP_201_CREATED,
    summary="登記包裹（產生 6 位數領取碼並通知該戶住戶）",
)
def register_package(body: PackageCreate, db: DbDep, clock: ClockDep, staff: StaffUser):
    return package_service.register_package(db, **body.model_dump(), staff=staff, now=clock.now())


@router.get("/packages", response_model=Page[PackageOut], summary="查詢包裹（住戶只會看到自家）")
def list_packages(
    db: DbDep,
    user: CurrentUser,
    unit_code: Annotated[UnitCode | None, Query()] = None,
    status: PackageStatus | None = None,
    date_from: Annotated[date | None, Query(description="登記日期起（台北時間，含）")] = None,
    date_to: Annotated[date | None, Query(description="登記日期迄（台北時間，含）")] = None,
    needs_attention: Annotated[bool | None, Query(description="冷藏需處理")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    filters = package_service.PackageFilter(
        unit_code=unit_code,
        status=status,
        date_from=date_from,
        date_to=date_to,
        needs_attention=needs_attention,
    )
    items, total = package_service.list_packages(db, filters, user, limit, offset)
    return Page[PackageOut](items=items, total=total)


@router.get(
    "/packages/by-code/{pickup_code}",
    response_model=PackageOut,
    summary="以領取碼查詢待領包裹",
)
def find_by_code(pickup_code: Annotated[str, Path(pattern=r"^\d{6}$")], db: DbDep, _: StaffUser):
    return package_service.find_pending_by_code(db, pickup_code)


@router.get("/packages/{package_id}", response_model=PackageOut, summary="包裹詳細資料")
def get_package(package_id: int, db: DbDep, user: CurrentUser):
    return package_service.get_package(db, package_id, user)


@router.post("/packages/{package_id}/pickup", response_model=PackageOut, summary="簽收")
def pick_up(package_id: int, body: PickupRequest, db: DbDep, clock: ClockDep, staff: StaffUser):
    package = package_service.get_package(db, package_id, staff)
    return pickup_service.pick_up(db, package, body, staff=staff, now=clock.now())


@router.post("/pickups/by-code", response_model=PackageOut, summary="以領取碼簽收")
def pick_up_by_code(body: PickupByCodeRequest, db: DbDep, clock: ClockDep, staff: StaffUser):
    package = package_service.find_pending_by_code(db, body.pickup_code)
    return pickup_service.pick_up(db, package, body, staff=staff, now=clock.now())


@router.post(
    "/packages/{package_id}/exception",
    response_model=PackageOut,
    summary="標記退回物流或遺失（領取碼立即失效）",
)
def mark_exception(
    package_id: int, body: ExceptionRequest, db: DbDep, clock: ClockDep, staff: StaffUser
):
    return package_service.mark_exception(
        db, package_id, status=body.status, reason=body.reason, staff=staff, now=clock.now()
    )
