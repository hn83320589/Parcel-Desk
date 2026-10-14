from tests.helpers import pickup_by_code, register


def create_proxy(client, world, *, as_user="alice", valid_until="2026-10-31T23:59:00", **extra):
    body = {"name": "外婆", "id_last4": "1234", "valid_until": valid_until, **extra}
    resp = client.post("/proxies", json=body, headers=world.headers(as_user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_pickup_by_code_records_picker_staff_counter_and_time(client, world, clock):
    pkg = register(client, world)
    clock.advance(hours=5)

    resp = pickup_by_code(
        client, world, pkg["pickup_code"], picker_user="amy", staff="staff_b", counter="B"
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "picked_up"
    pickup = body["pickup"]
    assert pickup["picker_type"] == "resident"
    assert pickup["picker_user_id"] == world.users["amy"].id
    assert pickup["picker_name"] == "Amy"
    assert pickup["staff_id"] == world.users["staff_b"].id
    assert pickup["counter"] == "B"
    assert pickup["picked_up_at"] == "2026-10-01T15:00:00+08:00"


def test_second_pickup_returns_409_and_record_unchanged(client, world, clock):
    pkg = register(client, world)
    first = pickup_by_code(client, world, pkg["pickup_code"]).json()["pickup"]
    clock.advance(minutes=30)

    by_id = client.post(
        f"/packages/{pkg['id']}/pickup",
        json={"counter": "B", "picker_type": "resident", "picker_user_id": world.users["amy"].id},
        headers=world.headers("staff_b"),
    )
    by_code = pickup_by_code(client, world, pkg["pickup_code"], picker_user="amy")

    assert by_id.status_code == 409
    assert by_code.status_code == 409
    after = client.get(f"/packages/{pkg['id']}", headers=world.headers("staff_a")).json()
    assert after["pickup"] == first


def test_resident_of_other_unit_cannot_pick_up(client, world):
    pkg = register(client, world, "A-12F-3")
    resp = pickup_by_code(client, world, pkg["pickup_code"], picker_user="bob")
    assert resp.status_code == 403
    assert resp.json()["code"] == "NOT_RESIDENT_OF_UNIT"


def test_valid_proxy_can_pick_up(client, world):
    proxy = create_proxy(client, world)
    assert proxy["is_valid"] is True
    pkg = register(client, world)

    resp = pickup_by_code(client, world, pkg["pickup_code"], proxy_id=proxy["id"])

    assert resp.status_code == 200
    assert resp.json()["pickup"]["picker_type"] == "proxy"
    assert resp.json()["pickup"]["picker_name"] == "外婆"


def test_expired_proxy_gets_403(client, world, clock):
    proxy = create_proxy(client, world, valid_until="2026-10-03T00:00:00")
    pkg = register(client, world)
    clock.advance(days=3)  # 10/4，已過期

    resp = pickup_by_code(client, world, pkg["pickup_code"], proxy_id=proxy["id"])

    assert resp.status_code == 403
    assert resp.json()["code"] == "PROXY_EXPIRED"
    still = client.get(f"/packages/{pkg['id']}", headers=world.headers("staff_a")).json()
    assert still["status"] == "pending"
    assert still["pickup"] is None


def test_revoked_or_other_units_proxy_gets_403(client, world):
    revoked = create_proxy(client, world)
    assert (
        client.delete(f"/proxies/{revoked['id']}", headers=world.headers("alice")).status_code
        == 200
    )
    bobs = create_proxy(client, world, as_user="bob", name="Bob 的同事")
    pkg = register(client, world, "A-12F-3")

    assert (
        pickup_by_code(client, world, pkg["pickup_code"], proxy_id=revoked["id"]).status_code == 403
    )
    resp = pickup_by_code(client, world, pkg["pickup_code"], proxy_id=bobs["id"])
    assert resp.status_code == 403
    assert resp.json()["code"] == "PROXY_NOT_OF_UNIT"


def test_proxy_permissions(client, world):
    alices = create_proxy(client, world)
    # 住戶看不到、也不能撤銷他戶代領人
    assert client.get("/proxies", headers=world.headers("bob")).json() == []
    assert (
        client.delete(f"/proxies/{alices['id']}", headers=world.headers("bob")).status_code == 404
    )
    # 管理員可查詢（簽收時選擇代領人），但不能新增
    listed = client.get(
        "/proxies?unit_code=A-12F-3&only_valid=true", headers=world.headers("staff_a")
    )
    assert [p["id"] for p in listed.json()] == [alices["id"]]
    body = {"unit_code": "A-12F-3", "name": "x", "valid_until": "2026-12-31T00:00:00"}
    assert client.post("/proxies", json=body, headers=world.headers("staff_a")).status_code == 403
    # 管委會可代為建立
    assert client.post("/proxies", json=body, headers=world.headers("admin")).status_code == 201


def test_unknown_pickup_code_returns_404(client, world):
    assert pickup_by_code(client, world, "000000").status_code == 404
