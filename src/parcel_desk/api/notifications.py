from typing import Annotated

from fastapi import APIRouter, Query

from parcel_desk.deps import CurrentUser, DbDep
from parcel_desk.models import NotificationKind
from parcel_desk.schemas.common import UnitCode
from parcel_desk.schemas.packages import NotificationOut
from parcel_desk.services import notifications as notification_service
from parcel_desk.services.units import get_unit

router = APIRouter(prefix="/notifications", tags=["通知紀錄"])


@router.get("", response_model=list[NotificationOut], summary="通知紀錄（住戶只會看到自家）")
def list_notifications(
    db: DbDep,
    user: CurrentUser,
    unit_code: Annotated[UnitCode | None, Query()] = None,
    kind: NotificationKind | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    unit = get_unit(db, unit_code) if unit_code else None
    return notification_service.list_notifications(
        db, user, unit=unit, kind=kind, limit=limit, offset=offset
    )


@router.get("/{notification_id}", response_model=NotificationOut, summary="單則通知")
def get_notification(notification_id: int, db: DbDep, user: CurrentUser):
    return notification_service.get_notification(db, notification_id, user)
