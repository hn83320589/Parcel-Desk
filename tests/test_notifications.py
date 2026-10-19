from tests.helpers import register


def arrival_notifications(client, world, unit_code="A-12F-3"):
    resp = client.get(
        f"/notifications?unit_code={unit_code}&kind=arrival", headers=world.headers("admin")
    )
    assert resp.status_code == 200
    return sorted(resp.json(), key=lambda n: n["id"])


def test_packages_within_ten_minutes_merge_into_one_notification(client, world, clock):
    ids = [register(client, world)["id"]]
    clock.advance(minutes=3)
    ids.append(register(client, world)["id"])
    clock.advance(minutes=6)  # 第 9 分鐘
    ids.append(register(client, world)["id"])

    notes = arrival_notifications(client, world)
    assert len(notes) == 1
    assert notes[0]["package_ids"] == ids
    assert notes[0]["title"] == "包裹到件通知（3 件）"

    clock.advance(minutes=2)  # 第 11 分鐘
    fourth = register(client, world)

    notes = arrival_notifications(client, world)
    assert len(notes) == 2
    assert notes[1]["package_ids"] == [fourth["id"]]


def test_window_is_fixed_from_first_package(client, world, clock):
    register(client, world)
    clock.advance(minutes=9)
    register(client, world)
    clock.advance(minutes=1)  # 恰好第 10 分鐘：視窗已結束
    register(client, world)
    assert [len(n["package_ids"]) for n in arrival_notifications(client, world)] == [2, 1]


def test_notification_goes_to_all_residents_and_not_merged_across_units(client, world):
    register(client, world, "A-12F-3")
    register(client, world, "B-5F-1")

    a_notes = arrival_notifications(client, world, "A-12F-3")
    b_notes = arrival_notifications(client, world, "B-5F-1")
    assert len(a_notes) == len(b_notes) == 1
    assert set(a_notes[0]["recipient_ids"]) == {world.users["alice"].id, world.users["amy"].id}
    assert b_notes[0]["recipient_ids"] == [world.users["bob"].id]


def test_notification_body_lists_pickup_codes(client, world):
    pkg = register(client, world, carrier="新竹物流", type="cold")
    note = arrival_notifications(client, world)[0]
    assert "新竹物流（冷藏）" in note["body"]
    assert pkg["pickup_code"] in note["body"]


def test_resident_only_sees_own_unit_notifications(client, world):
    register(client, world, "A-12F-3")
    other = register(client, world, "B-5F-1")
    other_note_id = arrival_notifications(client, world, "B-5F-1")[0]["id"]

    notes = client.get("/notifications", headers=world.headers("alice")).json()
    assert [n["unit_code"] for n in notes] == ["A-12F-3"]
    assert other["id"] not in notes[0]["package_ids"]
    resp = client.get(f"/notifications/{other_note_id}", headers=world.headers("alice"))
    assert resp.status_code == 404


def test_concurrent_registrations_for_same_unit_merge_into_one_notification(
    app, world, clock, monkeypatch
):
    """兩個櫃台交錯登記同一戶：A 已查完視窗、尚未 commit 時，B 開始登記。

    合併的正確性依賴 SQLite 的單一寫入鎖：A 寫入包裹時取得寫入鎖，B 寫入包裹時
    必須等 A commit，因此 B 查詢視窗時一定看得到 A 建立的通知。
    """
    import threading

    from sqlalchemy import select

    from parcel_desk.models import Notification, NotificationKind, PackageType
    from parcel_desk.services import packages as package_service

    a_ready, release_a = threading.Event(), threading.Event()
    original = package_service.notify_arrival

    def pausing_notify(session, package, now):
        notification = original(session, package, now)
        if threading.current_thread().name == "counter-A":
            a_ready.set()
            assert release_a.wait(timeout=5)
        return notification

    monkeypatch.setattr(package_service, "notify_arrival", pausing_notify)
    errors = []

    def register(staff):
        try:
            with app.state.session_factory() as s:
                package_service.register_package(
                    s,
                    unit_code="A-12F-3",
                    carrier="郵局",
                    type=PackageType.NORMAL,
                    staff=world.users[staff],
                    now=clock.now(),
                )
        except Exception as exc:  # 讓主執行緒看得到錯誤
            errors.append(exc)

    a = threading.Thread(target=register, args=("staff_a",), name="counter-A")
    b = threading.Thread(target=register, args=("staff_b",), name="counter-B")
    a.start()
    assert a_ready.wait(timeout=5)
    b.start()  # B 會卡在 SQLite 寫入鎖
    b.join(timeout=0.5)
    assert b.is_alive(), "B 應該在等 A 釋放寫入鎖"
    release_a.set()
    a.join(timeout=5)
    b.join(timeout=10)

    assert errors == []
    with app.state.session_factory() as s:
        notes = list(
            s.scalars(select(Notification).where(Notification.kind == NotificationKind.ARRIVAL))
        )
        assert len(notes) == 1
        assert len(notes[0].packages) == 2
