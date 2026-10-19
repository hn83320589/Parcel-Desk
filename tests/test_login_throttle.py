"""登入失敗次數限制：以「帳號 + 來源 IP」為單位，連續失敗 5 次鎖定 5 分鐘。"""

from datetime import UTC, datetime, timedelta

from parcel_desk.services.login_throttle import LoginThrottle

T0 = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)


def login(client, username="admin", password="password123"):
    return client.post("/auth/token", data={"username": username, "password": password})


def test_five_failures_lock_the_account_even_for_correct_password(client, world, clock):
    for _ in range(5):
        assert login(client, password="wrong-password").status_code == 401

    locked = login(client)  # 密碼正確也拒絕，否則鎖定沒有意義
    assert locked.status_code == 429
    assert locked.json()["code"] == "LOGIN_LOCKED"
    assert int(locked.headers["Retry-After"]) == 300

    clock.advance(minutes=4, seconds=59)
    assert login(client).status_code == 429
    clock.advance(seconds=1)
    assert login(client).status_code == 200


def test_success_resets_failure_count(client, world):
    for _ in range(4):
        login(client, password="wrong-password")
    assert login(client).status_code == 200
    for _ in range(4):
        login(client, password="wrong-password")
    assert login(client).status_code == 200


def test_lock_is_per_account(client, world):
    for _ in range(5):
        login(client, "admin", "wrong-password")
    assert login(client, "admin").status_code == 429
    assert login(client, "staff_a").status_code == 200


def test_unknown_usernames_are_throttled_too(client, world):
    for _ in range(5):
        login(client, "no-such-user", "x" * 8)
    assert login(client, "no-such-user", "x" * 8).status_code == 429


def test_lock_is_per_source_ip():
    throttle = LoginThrottle(max_failures=5, lockout=timedelta(minutes=5))
    for _ in range(5):
        throttle.record_failure(("admin", "10.0.0.5"), T0)
    assert throttle.locked_for(("admin", "10.0.0.5"), T0) == timedelta(minutes=5)
    assert throttle.locked_for(("admin", "10.0.0.6"), T0) is None


def test_memory_is_bounded():
    throttle = LoginThrottle(max_failures=5, lockout=timedelta(minutes=5), max_entries=100)
    for i in range(1_000):
        throttle.record_failure((f"user{i}", "10.0.0.1"), T0)
    assert len(throttle) <= 100
