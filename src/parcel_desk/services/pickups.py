from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from parcel_desk.errors import Forbidden
from parcel_desk.models import Package, PackageStatus, PickerType, Pickup, Proxy, Role, User
from parcel_desk.schemas.packages import PickupRequest
from parcel_desk.services.packages import ensure_pending


def _resolve_picker(session: Session, package: Package, req: PickupRequest, now: datetime) -> str:
    """確認領取人有權領取，回傳領取人姓名（存為快照）。"""
    if req.picker_type == PickerType.RESIDENT:
        resident = session.get(User, req.picker_user_id)
        if (
            resident is None
            or resident.role != Role.RESIDENT
            or not resident.is_active
            or resident.unit_id != package.unit_id
        ):
            raise Forbidden("領取人不是該戶住戶", code="NOT_RESIDENT_OF_UNIT")
        return resident.display_name

    proxy = session.get(Proxy, req.picker_proxy_id)
    if proxy is None or proxy.unit_id != package.unit_id:
        raise Forbidden("代領人不在該戶的代領名單中", code="PROXY_NOT_OF_UNIT")
    if not proxy.is_valid_at(now):
        raise Forbidden("代領人已過期或已被撤銷", code="PROXY_EXPIRED")
    return proxy.name


def pick_up(
    session: Session, package: Package, req: PickupRequest, *, staff: User, now: datetime
) -> Package:
    ensure_pending(package)
    picker_name = _resolve_picker(session, package, req, now)

    # 條件式更新：兩個櫃台同時簽收同一件時，只有一方會更新到資料列
    result = session.execute(
        update(Package)
        .where(Package.id == package.id, Package.status == PackageStatus.PENDING)
        .values(status=PackageStatus.PICKED_UP)
    )
    if result.rowcount == 0:
        session.rollback()
        session.refresh(package)
        ensure_pending(package)

    session.add(
        Pickup(
            package_id=package.id,
            picker_type=req.picker_type,
            picker_user_id=req.picker_user_id if req.picker_type == PickerType.RESIDENT else None,
            picker_proxy_id=req.picker_proxy_id if req.picker_type == PickerType.PROXY else None,
            picker_name=picker_name,
            staff_id=staff.id,
            counter=req.counter,
            picked_up_at=now,
        )
    )
    session.commit()
    session.refresh(package)
    return package
