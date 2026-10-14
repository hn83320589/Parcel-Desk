def register(client, world, unit_code="A-12F-3", staff="staff_a", **fields):
    body = {"unit_code": unit_code, "carrier": "黑貓宅急便", "type": "normal", **fields}
    resp = client.post("/packages", json=body, headers=world.headers(staff))
    assert resp.status_code == 201, resp.text
    return resp.json()


def pickup_by_code(
    client, world, code, *, picker_user="alice", proxy_id=None, staff="staff_a", counter="A"
):
    body = {"pickup_code": code, "counter": counter}
    if proxy_id is None:
        body |= {"picker_type": "resident", "picker_user_id": world.users[picker_user].id}
    else:
        body |= {"picker_type": "proxy", "picker_proxy_id": proxy_id}
    return client.post("/pickups/by-code", json=body, headers=world.headers(staff))
