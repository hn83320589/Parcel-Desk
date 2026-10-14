from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from parcel_desk.errors import Conflict, InvalidField, NotFound
from parcel_desk.models import Proxy, Role, Unit, User
from parcel_desk.services.units import get_unit, get_unit_for_input


def _target_unit(session: Session, actor: User, unit_code: str | None) -> Unit:
    """住戶只能管理自家代領人；管委會須指定戶號。"""
    if actor.role == Role.RESIDENT:
        if unit_code is not None and unit_code != actor.unit_code:
            raise InvalidField("unit_code", "住戶只能為自家指定代領人")
        return actor.unit
    if unit_code is None:
        raise InvalidField("unit_code", "請指定戶號")
    return get_unit_for_input(session, unit_code)


def create_proxy(
    session: Session,
    actor: User,
    *,
    unit_code: str | None,
    name: str,
    phone: str | None,
    id_last4: str | None,
    valid_from: datetime | None,
    valid_until: datetime,
    now: datetime,
) -> Proxy:
    unit = _target_unit(session, actor, unit_code)
    valid_from = valid_from or now
    if valid_until <= valid_from:
        raise InvalidField("valid_until", "到期時間必須晚於生效時間")
    proxy = Proxy(
        unit_id=unit.id,
        name=name,
        phone=phone,
        id_last4=id_last4,
        valid_from=valid_from,
        valid_until=valid_until,
        created_by=actor.id,
        created_at=now,
    )
    session.add(proxy)
    session.commit()
    return proxy


def list_proxies(
    session: Session, viewer: User, unit_code: str | None, *, only_valid_at: datetime | None
) -> list[Proxy]:
    stmt = select(Proxy).order_by(Proxy.id)
    if viewer.role == Role.RESIDENT:
        stmt = stmt.where(Proxy.unit_id == viewer.unit_id)
    if unit_code is not None:
        stmt = stmt.where(Proxy.unit_id == get_unit(session, unit_code).id)
    proxies = list(session.scalars(stmt).unique())
    if only_valid_at is not None:
        proxies = [p for p in proxies if p.is_valid_at(only_valid_at)]
    return proxies


def revoke_proxy(session: Session, actor: User, proxy_id: int, now: datetime) -> Proxy:
    proxy = session.get(Proxy, proxy_id)
    if proxy is None or (actor.role == Role.RESIDENT and proxy.unit_id != actor.unit_id):
        raise NotFound("代領人不存在", code="PROXY_NOT_FOUND")
    if proxy.revoked_at is not None:
        raise Conflict("代領人已被撤銷", code="PROXY_ALREADY_REVOKED")
    proxy.revoked_at = now
    session.commit()
    return proxy
