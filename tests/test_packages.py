import re

import pytest

from parcel_desk.models import PackageType
from parcel_desk.services.packages import register_package
from tests.helpers import register


def test_register_package_generates_six_digit_code(client, world):
    pkg = register(client, world, recipient_name="王小明", tracking_no="TW123", type="cold")
    assert re.fullmatch(r"\d{6}", pkg["pickup_code"])
    assert pkg["status"] == "pending"
    assert pkg["unit_code"] == "A-12F-3"
    assert pkg["type"] == "cold"
    assert pkg["registered_by"] == world.users["staff_a"].id
    assert pkg["registered_at"].endswith("+08:00")


def test_thousand_pending_packages_have_unique_codes(client, world):
    codes = {register(client, world)["pickup_code"] for _ in range(1000)}
    assert len(codes) == 1000


def test_code_generation_retries_on_collision(db, world, clock):
    codes = iter(["111111", "111111", "111111", "222222"])
    staff = world.users["staff_a"]

    first = register_package(
        db,
        unit_code="A-12F-3",
        carrier="7-11",
        type=PackageType.NORMAL,
        staff=staff,
        now=clock.now(),
        code_generator=lambda: next(codes),
    )
    second = register_package(
        db,
        unit_code="A-12F-3",
        carrier="7-11",
        type=PackageType.NORMAL,
        staff=staff,
        now=clock.now(),
        code_generator=lambda: next(codes),
    )

    assert (first.pickup_code, second.pickup_code) == ("111111", "222222")


@pytest.mark.parametrize("bad_code", ["A12F3", "A-12-3", "a-12F-3", "A-0F-1", "AB-1F-1"])
def test_register_with_malformed_unit_code_returns_422(client, world, bad_code):
    body = {"unit_code": bad_code, "carrier": "郵局", "type": "normal"}
    resp = client.post("/packages", json=body, headers=world.headers("staff_a"))
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "unit_code"]


def test_register_to_unknown_unit_returns_422(client, world):
    body = {"unit_code": "A-99F-9", "carrier": "郵局", "type": "normal"}
    resp = client.post("/packages", json=body, headers=world.headers("staff_a"))
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "unit_code"]


def test_resident_cannot_register_package(client, world):
    body = {"unit_code": "A-12F-3", "carrier": "郵局", "type": "normal"}
    assert client.post("/packages", json=body, headers=world.headers("alice")).status_code == 403


def test_staff_filters_by_unit_status_and_date(client, world, clock):
    register(client, world, "A-12F-3")
    clock.advance(days=1)
    register(client, world, "A-12F-3")
    register(client, world, "B-5F-1")
    h = world.headers("staff_b")

    assert client.get("/packages", headers=h).json()["total"] == 3
    assert client.get("/packages?unit_code=A-12F-3", headers=h).json()["total"] == 2
    assert client.get("/packages?status=picked_up", headers=h).json()["total"] == 0
    # START 為 10/1；前進一天後登記的兩件屬於 10/2
    resp = client.get("/packages?date_from=2026-10-02&date_to=2026-10-02", headers=h)
    assert resp.json()["total"] == 2
    bad = client.get("/packages?unit_code=A12F3", headers=h)
    assert bad.status_code == 422
    assert bad.json()["detail"][0]["loc"] == ["query", "unit_code"]


def test_resident_sees_only_own_unit_and_gets_404_for_others(client, world):
    own = register(client, world, "A-12F-3")
    other = register(client, world, "B-5F-1")
    h = world.headers("alice")

    listing = client.get("/packages", headers=h).json()
    assert [p["id"] for p in listing["items"]] == [own["id"]]
    assert client.get(f"/packages/{own['id']}", headers=h).status_code == 200
    assert client.get(f"/packages/{other['id']}", headers=h).status_code == 404
    # 即使帶 unit_code 參數也看不到他戶
    resp = client.get("/packages?unit_code=B-5F-1", headers=h).json()
    assert resp["total"] == 0
    # 管理員可以查所有戶
    assert (
        client.get(f"/packages/{other['id']}", headers=world.headers("staff_a")).status_code == 200
    )
