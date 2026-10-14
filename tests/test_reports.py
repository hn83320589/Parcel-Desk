from datetime import datetime

from parcel_desk.clock import LOCAL_TZ
from parcel_desk.services.reminders import run_reminders
from tests.helpers import pickup_by_code, register


def at(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=LOCAL_TZ)


def build_october(client, world, db, clock):
    """
    A-12F-3（10 月登記 4 件）
      p1 10/1 10:00 登記，10/1 12:00 領   → 2.00 小時
      p2 10/1 10:00 登記，10/2 15:30 領   → 29.50 小時
      p3 10/2 08:00 登記，10/10 09:30 領  → 193.50 小時（8 天又 1.5 小時），逾期（超過 10/9 09:00）
      p4 10/3 08:00 登記，未領            → 報表時間 10/20 時已逾期
    B-5F-1（10 月登記 1 件）
      c1 10/5 10:00 冷藏登記，10/8 10:00 領 → 72 小時，逾期且需處理
    月界：9/30 23:30 與 11/1 00:30（台北時間）登記者不屬於 10 月
    """
    clock.set(at(9, 30, 23, 30))
    register(client, world)
    clock.set(at(10, 1, 10))
    p1, p2 = register(client, world), register(client, world)
    clock.set(at(10, 1, 12))
    pickup_by_code(client, world, p1["pickup_code"])
    clock.set(at(10, 2, 8))
    p3 = register(client, world)
    clock.set(at(10, 2, 15, 30))
    pickup_by_code(client, world, p2["pickup_code"])
    clock.set(at(10, 3, 8))
    register(client, world)
    clock.set(at(10, 5, 10))
    c1 = register(client, world, "B-5F-1", type="cold")
    clock.set(at(10, 7, 10))
    run_reminders(db, clock.now())  # 冷藏滿 48 小時 → 需處理
    clock.set(at(10, 8, 10))
    pickup_by_code(client, world, c1["pickup_code"], picker_user="bob")
    clock.set(at(10, 10, 9, 30))
    pickup_by_code(client, world, p3["pickup_code"])
    clock.set(at(11, 1, 0, 30))
    register(client, world)
    clock.set(at(10, 20, 12))


def test_monthly_report_matches_hand_calculation(client, world, db, clock):
    build_october(client, world, db, clock)

    resp = client.get("/reports/monthly?month=2026-10", headers=world.headers("admin"))

    assert resp.status_code == 200
    report = resp.json()
    rows = {r["unit_code"]: r for r in report["rows"]}
    assert rows["A-12F-3"] == {
        "unit_code": "A-12F-3",
        "received": 4,
        "picked_up": 3,
        "avg_pickup_hours": 75.0,  # (2 + 29.5 + 193.5) / 3
        "overdue": 2,
        "cold_needs_attention": 0,
    }
    assert rows["B-5F-1"] == {
        "unit_code": "B-5F-1",
        "received": 1,
        "picked_up": 1,
        "avg_pickup_hours": 72.0,
        "overdue": 1,
        "cold_needs_attention": 1,
    }
    assert report["total"] == {
        "unit_code": "合計",
        "received": 5,
        "picked_up": 4,
        "avg_pickup_hours": 74.25,  # (2 + 29.5 + 193.5 + 72) / 4
        "overdue": 3,
        "cold_needs_attention": 1,
    }


def test_month_boundary_uses_taipei_time(client, world, db, clock):
    build_october(client, world, db, clock)
    h = world.headers("admin")
    assert client.get("/reports/monthly?month=2026-09", headers=h).json()["total"]["received"] == 1
    assert client.get("/reports/monthly?month=2026-11", headers=h).json()["total"]["received"] == 1


def test_csv_has_bom_and_opens_in_excel_without_mojibake(client, world, db, clock):
    build_october(client, world, db, clock)

    resp = client.get("/reports/monthly.csv?month=2026-10", headers=world.headers("admin"))

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="parcel-report-2026-10.csv"' in resp.headers["content-disposition"]
    assert resp.content.startswith(b"\xef\xbb\xbf")
    lines = resp.content.decode("utf-8-sig").split("\r\n")
    assert lines[0] == "戶號,收件數,已領件數,平均領取時間（小時）,逾期件數,冷藏需處理件數"
    assert lines[1] == "A-12F-3,4,3,75.00,2,0"
    assert lines[3] == "合計,5,4,74.25,3,1"


def test_report_is_admin_only_and_validates_month(client, world):
    assert (
        client.get("/reports/monthly?month=2026-10", headers=world.headers("staff_a")).status_code
        == 403
    )
    bad = client.get("/reports/monthly?month=2026-13", headers=world.headers("admin"))
    assert bad.status_code == 422
    assert bad.json()["detail"][0]["loc"] == ["query", "month"]


def test_empty_month_has_null_average(client, world):
    report = client.get("/reports/monthly?month=2026-01", headers=world.headers("admin")).json()
    assert report["rows"] == []
    assert report["total"]["received"] == 0
    assert report["total"]["avg_pickup_hours"] is None
