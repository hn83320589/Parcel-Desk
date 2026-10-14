from datetime import datetime

from sqlalchemy import func, select

from parcel_desk.clock import LOCAL_TZ
from parcel_desk.models import (
    Notification,
    NotificationKind,
    Package,
    PackageReminder,
    PackageType,
)
from parcel_desk.services.reminders import run_reminders
from tests.helpers import pickup_by_code, register


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """2026 年 10 月某日的台北時間。"""
    return datetime(2026, 10, day, hour, minute, tzinfo=LOCAL_TZ)


def count(db, kind: NotificationKind) -> int:
    return db.scalar(select(func.count()).where(Notification.kind == kind))


def run_at(db, clock, when: datetime):
    clock.set(when)
    return run_reminders(db, clock.now())


def test_normal_package_reminded_from_day_7_at_9am_once_per_day(client, world, db, clock):
    register(client, world, type="normal")  # 10/1 10:00 登記
    kind = NotificationKind.OVERDUE_REMINDER

    assert run_at(db, clock, at(7, 23, 59)).overdue == 0  # 第 6 天
    assert run_at(db, clock, at(8, 8, 59)).overdue == 0  # 第 7 天，09:00 前
    assert count(db, kind) == 0

    assert run_at(db, clock, at(8, 9, 0)).overdue == 1  # 第 7 天 09:00
    assert count(db, kind) == 1

    assert run_at(db, clock, at(8, 9, 10)).overdue == 0  # 同一天不重複
    assert run_at(db, clock, at(8, 18, 0)).overdue == 0
    assert count(db, kind) == 1

    assert run_at(db, clock, at(9, 9, 0)).overdue == 1  # 隔天再提醒
    assert count(db, kind) == 2


def test_late_start_catches_up_same_day_reminder(client, world, db, clock):
    register(client, world, type="large")
    # 電腦 10/8 中午才開機：第一次執行就補送當天提醒
    assert run_at(db, clock, at(8, 12, 30)).overdue == 1


def test_picked_up_package_is_not_reminded(client, world, db, clock):
    pkg = register(client, world)
    pickup_by_code(client, world, pkg["pickup_code"])
    assert run_at(db, clock, at(9, 9, 0)).overdue == 0


def test_overdue_packages_of_same_unit_share_one_reminder(client, world, db, clock):
    ids = {register(client, world)["id"], register(client, world)["id"]}
    register(client, world, "B-5F-1")

    run_at(db, clock, at(8, 9, 0))

    notes = list(
        db.scalars(
            select(Notification)
            .where(Notification.kind == NotificationKind.OVERDUE_REMINDER)
            .order_by(Notification.id)
        )
    )
    assert [n.unit.code for n in notes] == ["A-12F-3", "B-5F-1"]
    assert set(notes[0].package_ids) == ids
    assert {u.username for u in notes[0].recipients} == {"alice", "amy"}


def test_cold_package_24h_reminder_and_48h_needs_attention(client, world, db, clock):
    pkg = register(client, world, type="cold")  # 10/1 10:00

    result = run_at(db, clock, at(2, 9, 59))  # 23h59m
    assert (result.cold, result.needs_attention) == (0, 0)

    assert run_at(db, clock, at(2, 10, 0)).cold == 1  # 滿 24 小時
    assert run_at(db, clock, at(2, 20, 0)).cold == 0  # 只提醒一次
    assert count(db, NotificationKind.COLD_REMINDER) == 1

    assert run_at(db, clock, at(3, 9, 59)).needs_attention == 0  # 47h59m
    assert db.get(Package, pkg["id"]).needs_attention_at is None

    assert run_at(db, clock, at(3, 10, 0)).needs_attention == 1  # 滿 48 小時
    db.expire_all()
    assert db.get(Package, pkg["id"]).needs_attention_at is not None
    note = db.scalar(
        select(Notification).where(Notification.kind == NotificationKind.NEEDS_ATTENTION)
    )
    assert [u.username for u in note.recipients] == ["admin"]

    assert run_at(db, clock, at(4, 10, 0)).needs_attention == 0
    assert count(db, NotificationKind.NEEDS_ATTENTION) == 1


def test_needs_attention_package_appears_in_filter_and_can_still_be_picked_up(
    client, world, db, clock
):
    pkg = register(client, world, type="cold")
    run_at(db, clock, at(3, 10, 0))

    listed = client.get("/packages?needs_attention=true", headers=world.headers("staff_a")).json()
    assert [p["id"] for p in listed["items"]] == [pkg["id"]]
    assert pickup_by_code(client, world, pkg["pickup_code"]).status_code == 200


def test_cold_package_has_no_daily_7_day_reminder(client, world, db, clock):
    register(client, world, type="cold")
    run_at(db, clock, at(8, 9, 0))
    reminders = set(db.scalars(select(PackageReminder.kind)))
    assert count(db, NotificationKind.OVERDUE_REMINDER) == 0
    assert {r.value for r in reminders} == {"cold_24h", "cold_48h"}


def test_resident_does_not_see_admin_only_notifications(client, world, db, clock):
    register(client, world, type=PackageType.COLD.value)
    run_at(db, clock, at(3, 10, 0))
    kinds = {n["kind"] for n in client.get("/notifications", headers=world.headers("alice")).json()}
    assert kinds == {"arrival", "cold_reminder"}


def test_admin_can_trigger_reminders_via_api(client, world, clock):
    register(client, world)
    clock.set(at(8, 9, 0))
    resp = client.post("/admin/run-reminders", headers=world.headers("admin"))
    assert resp.status_code == 200
    assert resp.json() == {"overdue": 1, "cold": 0, "needs_attention": 0}
    assert client.post("/admin/run-reminders", headers=world.headers("staff_a")).status_code == 403
