from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from parcel_desk.deps import ClockDep, CurrentUser, DbDep, require_roles
from parcel_desk.models import Role, User
from parcel_desk.schemas.common import UnitCode
from parcel_desk.schemas.proxies import ProxyCreate, ProxyOut
from parcel_desk.services import proxies as proxy_service

router = APIRouter(prefix="/proxies", tags=["代領人"])

# 新增、撤銷：住戶（自家）與管委會；管理員只能查詢（簽收時選擇代領人）
ProxyManager = Annotated[User, Depends(require_roles(Role.ADMIN, Role.RESIDENT))]


@router.get("", response_model=list[ProxyOut], summary="代領人名單（住戶只會看到自家）")
def list_proxies(
    db: DbDep,
    user: CurrentUser,
    clock: ClockDep,
    unit_code: Annotated[UnitCode | None, Query()] = None,
    only_valid: Annotated[bool, Query(description="只列出目前有效者")] = False,
):
    now = clock.now()
    proxies = proxy_service.list_proxies(
        db, user, unit_code, only_valid_at=now if only_valid else None
    )
    return [ProxyOut.build(p, now) for p in proxies]


@router.post("", response_model=ProxyOut, status_code=status.HTTP_201_CREATED, summary="新增代領人")
def create_proxy(body: ProxyCreate, db: DbDep, clock: ClockDep, user: ProxyManager):
    now = clock.now()
    proxy = proxy_service.create_proxy(db, user, **body.model_dump(), now=now)
    return ProxyOut.build(proxy, now)


@router.delete("/{proxy_id}", response_model=ProxyOut, summary="撤銷代領人")
def revoke_proxy(proxy_id: int, db: DbDep, clock: ClockDep, user: ProxyManager):
    now = clock.now()
    return ProxyOut.build(proxy_service.revoke_proxy(db, user, proxy_id, now), now)
