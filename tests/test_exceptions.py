import pytest

from parcel_desk.models import PackageType
from parcel_desk.services.packages import register_package
from tests.helpers import pickup_by_code, register


def mark(client, world, package_id, status="returned", reason="地址錯誤，物流取回"):
    return client.post(
        f"/packages/{package_id}/exception",
        json={"status": status, "reason": reason},
        headers=world.headers("staff_a"),
    )


@pytest.mark.parametrize("status", ["returned", "lost"])
def test_marked_package_cannot_be_picked_up_with_its_code(client, world, status):
    pkg = register(client, world)

    resp = mark(client, world, pkg["id"], status)
    assert resp.status_code == 200
    assert resp.json()["status"] == status
    assert resp.json()["exception_reason"] == "地址錯誤，物流取回"

    pickup = pickup_by_code(client, world, pkg["pickup_code"])
    assert pickup.status_code == 409
    assert pickup.json()["code"] == "PICKUP_CODE_INACTIVE"
    by_id = client.post(
        f"/packages/{pkg['id']}/pickup",
        json={"counter": "A", "picker_type": "resident", "picker_user_id": world.users["alice"].id},
        headers=world.headers("staff_a"),
    )
    assert by_id.status_code == 409


def test_released_code_can_be_reused_by_new_package(client, world, db, clock):
    old = register(client, world)
    mark(client, world, old["id"], "lost", "櫃台找不到")

    new = register_package(
        db,
        unit_code="B-5F-1",
        carrier="郵局",
        type=PackageType.NORMAL,
        staff=world.users["staff_a"],
        now=clock.now(),
        code_generator=lambda: old["pickup_code"],
    )
    assert new.pickup_code == old["pickup_code"]

    # 用同一組碼簽收，領到的是新包裹（由 B-5F-1 住戶領取）
    resp = pickup_by_code(client, world, old["pickup_code"], picker_user="bob")
    assert resp.status_code == 200
    assert resp.json()["id"] == new.id
    old_after = client.get(f"/packages/{old['id']}", headers=world.headers("staff_a")).json()
    assert old_after["status"] == "lost"


def test_picked_up_code_can_also_be_reused(client, world, db, clock):
    old = register(client, world)
    assert pickup_by_code(client, world, old["pickup_code"]).status_code == 200
    new = register_package(
        db,
        unit_code="A-12F-3",
        carrier="郵局",
        type=PackageType.NORMAL,
        staff=world.users["staff_a"],
        now=clock.now(),
        code_generator=lambda: old["pickup_code"],
    )
    assert new.pickup_code == old["pickup_code"]


@pytest.mark.parametrize("reason", ["", "   "])
def test_reason_is_required(client, world, reason):
    pkg = register(client, world)
    resp = mark(client, world, pkg["id"], reason=reason)
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "reason"]


def test_only_pending_package_can_be_marked(client, world):
    pkg = register(client, world)
    pickup_by_code(client, world, pkg["pickup_code"])
    assert mark(client, world, pkg["id"]).status_code == 409


def test_pending_is_not_a_valid_exception_status(client, world):
    pkg = register(client, world)
    assert mark(client, world, pkg["id"], status="pending").status_code == 422
