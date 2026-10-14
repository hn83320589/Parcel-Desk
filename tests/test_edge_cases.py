"""邊界情境：兩櫃台同時操作、帳號管理、資料保護、輸入驗證。"""

import pytest
from sqlalchemy import func, select

from parcel_desk.errors import Conflict, Unavailable
from parcel_desk.models import Counter, Package, PackageStatus, PackageType, PickerType, Pickup
from parcel_desk.schemas.packages import PickupRequest
from parcel_desk.services.packages import mark_exception, register_package
from parcel_desk.services.pickup_codes import allocate_code
from parcel_desk.services.pickups import pick_up
from tests.helpers import pickup_by_code, register


def resident_request(world, counter=Counter.A):
    return PickupRequest(
        counter=counter, picker_type=PickerType.RESIDENT, picker_user_id=world.users["alice"].id
    )


def test_two_counters_picking_up_same_package_only_one_succeeds(client, app, world, clock):
    """A、B 櫃台同時讀到「待領」，各自送出簽收：條件式更新只讓一方成功。"""
    pkg_id = register(client, world)["id"]
    factory = app.state.session_factory
    with factory() as counter_a, factory() as counter_b:
        pkg_a = counter_a.get(Package, pkg_id)
        pkg_b = counter_b.get(Package, pkg_id)  # 兩邊都看到 pending

        pick_up(
            counter_a, pkg_a, resident_request(world), staff=world.users["staff_a"], now=clock.now()
        )
        with pytest.raises(Conflict):
            pick_up(
                counter_b,
                pkg_b,
                resident_request(world, Counter.B),
                staff=world.users["staff_b"],
                now=clock.now(),
            )

    with factory() as check:
        pickups = list(check.scalars(select(Pickup).where(Pickup.package_id == pkg_id)))
        assert len(pickups) == 1
        assert pickups[0].counter == Counter.A


def test_pickup_and_mark_lost_at_same_time_only_one_succeeds(client, app, world, clock):
    pkg_id = register(client, world)["id"]
    factory = app.state.session_factory
    with factory() as counter_a, factory() as counter_b:
        stale = counter_b.get(Package, pkg_id)
        counter_a.get(Package, pkg_id)
        mark_exception(
            counter_a,
            pkg_id,
            status=PackageStatus.LOST,
            reason="找不到",
            staff=world.users["staff_a"],
            now=clock.now(),
        )
        with pytest.raises(Conflict):
            pick_up(
                counter_b,
                stale,
                resident_request(world),
                staff=world.users["staff_b"],
                now=clock.now(),
            )
    with factory() as check:
        assert check.get(Package, pkg_id).status == PackageStatus.LOST
        assert check.scalar(select(func.count()).select_from(Pickup)) == 0


def test_code_space_exhausted_returns_unavailable(db, world, clock):
    register_package(
        db,
        unit_code="A-12F-3",
        carrier="郵局",
        type=PackageType.NORMAL,
        staff=world.users["staff_a"],
        now=clock.now(),
        code_generator=lambda: "999999",
    )
    with pytest.raises(Unavailable):
        allocate_code(db, generator=lambda: "999999")


def test_deactivated_user_is_rejected_immediately(client, world):
    headers = world.headers("alice")
    assert client.get("/auth/me", headers=headers).status_code == 200

    resp = client.patch(
        f"/users/{world.users['alice'].id}",
        json={"is_active": False},
        headers=world.headers("admin"),
    )
    assert resp.status_code == 200

    # 已簽發的 token 也立即失效（每次請求都重新讀取帳號狀態）
    assert client.get("/auth/me", headers=headers).status_code == 401
    login = client.post("/auth/token", data={"username": "alice", "password": "password123"})
    assert login.status_code == 401


def test_admin_resets_password(client, world):
    client.patch(
        f"/users/{world.users['bob'].id}",
        json={"password": "new-password-1"},
        headers=world.headers("admin"),
    )
    assert (
        client.post("/auth/token", data={"username": "bob", "password": "password123"}).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/token", data={"username": "bob", "password": "new-password-1"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    ("body", "status", "field"),
    [
        ({"role": "staff", "unit_code": "A-12F-3"}, 422, "unit_code"),  # 管理員不屬於任何戶
        ({"role": "resident"}, 422, "unit_code"),  # 住戶必須指定戶號
        ({"role": "staff", "username": "admin"}, 409, None),  # 帳號重複
        ({"role": "staff", "password": "short"}, 422, "password"),
    ],
)
def test_user_creation_rules(client, world, body, status, field):
    payload = {"username": "newbie", "password": "password123", "display_name": "新人", **body}
    resp = client.post("/users", json=payload, headers=world.headers("admin"))
    assert resp.status_code == status
    if field:
        assert resp.json()["detail"][0]["loc"] == ["body", field]


def test_only_admin_manages_accounts(client, world):
    assert client.get("/users", headers=world.headers("staff_a")).status_code == 403
    users = client.get("/users?role=resident", headers=world.headers("admin")).json()
    assert {u["username"] for u in users} == {"alice", "amy", "bob"}


def test_unit_listing_and_deletion_rules(client, world):
    h_admin = world.headers("admin")
    assert client.post("/units", json={"code": "B-7F-2"}, headers=h_admin).status_code == 201
    codes = [
        u["code"] for u in client.get("/units?building=B", headers=world.headers("staff_a")).json()
    ]
    assert codes == ["B-5F-1", "B-7F-2"]
    assert client.get("/units/B-7F-2", headers=world.headers("staff_a")).status_code == 200

    # 有住戶的戶別不能刪；空戶可刪
    assert client.delete("/units/A-12F-3", headers=h_admin).status_code == 409
    assert client.delete("/units/B-7F-2", headers=h_admin).status_code == 204
    assert client.get("/units/B-7F-2", headers=h_admin).status_code == 404


def test_pickup_request_requires_matching_picker_field(client, world):
    pkg = register(client, world)
    resp = client.post(
        f"/packages/{pkg['id']}/pickup",
        json={"counter": "A", "picker_type": "proxy", "picker_user_id": world.users["alice"].id},
        headers=world.headers("staff_a"),
    )
    assert resp.status_code == 422
    bad_counter = client.post(
        f"/packages/{pkg['id']}/pickup",
        json={"counter": "C", "picker_type": "resident", "picker_user_id": world.users["alice"].id},
        headers=world.headers("staff_a"),
    )
    assert bad_counter.status_code == 422


def test_lookup_by_code_returns_pending_package_for_staff_only(client, world):
    pkg = register(client, world)
    found = client.get(f"/packages/by-code/{pkg['pickup_code']}", headers=world.headers("staff_b"))
    assert found.json()["id"] == pkg["id"]
    assert (
        client.get(
            f"/packages/by-code/{pkg['pickup_code']}", headers=world.headers("alice")
        ).status_code
        == 403
    )
    pickup_by_code(client, world, pkg["pickup_code"])
    assert (
        client.get(
            f"/packages/by-code/{pkg['pickup_code']}", headers=world.headers("staff_b")
        ).status_code
        == 409
    )


def test_proxy_validity_range_is_validated(client, world):
    body = {"name": "x", "valid_from": "2026-10-10T00:00:00", "valid_until": "2026-10-09T00:00:00"}
    assert client.post("/proxies", json=body, headers=world.headers("alice")).status_code == 422
    other_unit = {"unit_code": "B-5F-1", "name": "x", "valid_until": "2026-12-31T00:00:00"}
    resp = client.post("/proxies", json=other_unit, headers=world.headers("alice"))
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "unit_code"]
