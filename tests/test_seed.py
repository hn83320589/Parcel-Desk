from datetime import UTC, datetime

from sqlalchemy import func, select

from parcel_desk.models import (
    Notification,
    Package,
    PackageStatus,
    PickerType,
    Pickup,
    Proxy,
    Unit,
)
from parcel_desk.seed import seed

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)  # 台北 14:00


def test_seed_covers_required_data(db):
    summary = seed(db, NOW)

    buildings = set(db.scalars(select(Unit.building)))
    assert buildings == {"A", "B"}
    assert summary.units >= 20
    assert sum(summary.packages.values()) >= 50
    assert set(summary.packages) == {s.value for s in PackageStatus}
    assert db.scalar(select(func.count()).where(Package.needs_attention_at.is_not(None))) >= 1
    proxies = list(db.scalars(select(Proxy)))
    assert any(p.is_valid_at(NOW) for p in proxies)
    assert any(p.valid_until < NOW for p in proxies)
    # 固定示範資料：A-12F-3 最近 10 分鐘內的 3 件合併成 1 則通知
    latest = db.scalar(
        select(Notification)
        .where(Notification.unit.has(code="A-12F-3"))
        .order_by(Notification.id.desc())
        .limit(1)
    )
    assert len(latest.packages) == 3


def test_seed_accounts_can_log_in(client, db):
    seed(db, NOW)
    for username, password in [
        ("admin", "admin1234"),
        ("staff_a", "staff1234"),
        ("a12f3_1", "resident1234"),
    ]:
        resp = client.post("/auth/token", data={"username": username, "password": password})
        assert resp.status_code == 200, username


def test_seed_includes_proxy_pickup(db):
    seed(db, NOW)
    assert db.scalar(select(func.count()).where(Pickup.picker_type == PickerType.PROXY)) >= 1
