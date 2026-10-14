def test_login_returns_jwt_for_each_role(client, world):
    for username in ("admin", "staff_a", "alice"):
        resp = client.post("/auth/token", data={"username": username, "password": "password123"})
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["username"] == username


def test_wrong_password_and_missing_token_return_401(client, world):
    resp = client.post("/auth/token", data={"username": "admin", "password": "nope-nope"})
    assert resp.status_code == 401
    assert client.get("/auth/me").status_code == 401


def test_invalid_unit_code_returns_422_with_field(client, world):
    resp = client.post("/units", json={"code": "A12F3"}, headers=world.headers("admin"))
    assert resp.status_code == 422
    error = resp.json()["detail"][0]
    assert error["loc"] == ["body", "code"]
    assert "戶號格式錯誤" in error["msg"]


def test_admin_creates_unit_and_staff_cannot(client, world):
    resp = client.post("/units", json={"code": "A-3F-2"}, headers=world.headers("admin"))
    assert resp.status_code == 201
    assert resp.json() == {
        "id": resp.json()["id"],
        "code": "A-3F-2",
        "building": "A",
        "floor": 3,
        "number": 2,
    }
    resp = client.post("/units", json={"code": "A-3F-1"}, headers=world.headers("staff_a"))
    assert resp.status_code == 403
    dup = client.post("/units", json={"code": "A-3F-2"}, headers=world.headers("admin"))
    assert dup.status_code == 409


def test_resident_account_requires_existing_unit(client, world):
    body = {
        "username": "carol",
        "password": "password123",
        "display_name": "Carol",
        "role": "resident",
        "unit_code": "A-99F-9",
    }
    resp = client.post("/users", json=body, headers=world.headers("admin"))
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "unit_code"]


def test_resident_cannot_list_other_units_residents(client, world):
    own = client.get("/units/A-12F-3/residents", headers=world.headers("alice"))
    assert own.status_code == 200
    assert {r["display_name"] for r in own.json()} == {"Alice", "Amy"}
    other = client.get("/units/B-5F-1/residents", headers=world.headers("alice"))
    assert other.status_code == 404
