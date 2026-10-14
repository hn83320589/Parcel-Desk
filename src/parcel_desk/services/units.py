from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from parcel_desk.errors import Conflict, InvalidField, NotFound
from parcel_desk.models import Package, Role, Unit, User
from parcel_desk.schemas.common import parse_unit_code


def create_unit(session: Session, code: str, now: datetime) -> Unit:
    building, floor, number = parse_unit_code(code)
    if session.scalar(select(exists().where(Unit.code == code))):
        raise Conflict(f"戶號 {code} 已存在", code="UNIT_EXISTS")
    unit = Unit(code=code, building=building, floor=floor, number=number, created_at=now)
    session.add(unit)
    session.commit()
    return unit


def list_units(session: Session, building: str | None = None) -> list[Unit]:
    stmt = select(Unit).order_by(Unit.building, Unit.floor, Unit.number)
    if building:
        stmt = stmt.where(Unit.building == building)
    return list(session.scalars(stmt))


def get_unit(session: Session, code: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.code == code))
    if unit is None:
        raise NotFound(f"戶號 {code} 不存在", code="UNIT_NOT_FOUND")
    return unit


def get_unit_for_input(session: Session, code: str, field: str = "unit_code") -> Unit:
    """用於 request body：戶別不存在時回 422 並指出欄位。"""
    unit = session.scalar(select(Unit).where(Unit.code == code))
    if unit is None:
        raise InvalidField(field, f"戶號 {code} 不存在")
    return unit


def delete_unit(session: Session, code: str) -> None:
    unit = get_unit(session, code)
    in_use = session.scalar(
        select(exists().where(Package.unit_id == unit.id) | exists().where(User.unit_id == unit.id))
    )
    if in_use:
        raise Conflict("此戶已有住戶或包裹紀錄，無法刪除", code="UNIT_IN_USE")
    session.delete(unit)
    session.commit()


def list_residents(session: Session, unit: Unit) -> list[User]:
    stmt = (
        select(User)
        .where(User.unit_id == unit.id, User.role == Role.RESIDENT, User.is_active.is_(True))
        .order_by(User.id)
    )
    return list(session.scalars(stmt))
