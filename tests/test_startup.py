"""啟動模式：正式模式不載入示範資料；demo 模式用獨立資料庫且建置具原子性。"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from parcel_desk import seed as seed_module
from parcel_desk.cli import main, prepare_production
from parcel_desk.config import Settings, get_settings
from parcel_desk.main import create_app
from parcel_desk.models import Package, Role, Unit, User
from parcel_desk.seed import build_demo_database

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)


def count(db_path, model) -> int:
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as s:
        n = s.scalar(select(func.count()).select_from(model))
    engine.dispose()
    return n


@pytest.fixture
def prod_settings(tmp_path):
    return Settings(database_path=tmp_path / "data" / "parcel_desk.db", scheduler_enabled=False)


def test_production_start_creates_only_one_admin_and_no_demo_data(prod_settings):
    password = prepare_production(prod_settings)

    assert password is not None and len(password) >= 12
    db = prod_settings.database_path
    assert count(db, Unit) == 0
    assert count(db, Package) == 0
    engine = create_engine(f"sqlite:///{db}")
    with Session(engine) as s:
        users = list(s.scalars(select(User)))
    engine.dispose()
    assert [(u.username, u.role, u.must_change_password) for u in users] == [
        ("admin", Role.ADMIN, True)
    ]


def test_production_restart_does_not_create_another_admin(prod_settings):
    prepare_production(prod_settings)
    assert prepare_production(prod_settings) is None
    assert count(prod_settings.database_path, User) == 1


def test_bootstrap_admin_must_change_password_before_using_api(prod_settings, clock):
    password = prepare_production(prod_settings)
    with TestClient(create_app(prod_settings, clock=clock)) as client:
        token = client.post("/auth/token", data={"username": "admin", "password": password})
        h = {"Authorization": f"Bearer {token.json()['access_token']}"}

        blocked = client.get("/units", headers=h)
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
        assert client.get("/auth/me", headers=h).json()["must_change_password"] is True

        wrong = client.post(
            "/auth/change-password",
            json={"current_password": "nope", "new_password": "new-secret-123"},
            headers=h,
        )
        assert wrong.status_code == 422
        same = client.post(
            "/auth/change-password",
            json={"current_password": password, "new_password": password},
            headers=h,
        )
        assert same.status_code == 422

        ok = client.post(
            "/auth/change-password",
            json={"current_password": password, "new_password": "new-secret-123"},
            headers=h,
        )
        assert ok.status_code == 204
        assert client.get("/units", headers=h).status_code == 200
        old = client.post("/auth/token", data={"username": "admin", "password": password})
        assert old.status_code == 401


def test_demo_build_is_atomic_when_interrupted(tmp_path, monkeypatch):
    target = tmp_path / "demo.db"
    real_seed = seed_module.seed

    def interrupted(session, now, **kwargs):
        seed_module._create_accounts(session, now)  # 先寫入部分資料再中斷
        raise KeyboardInterrupt

    monkeypatch.setattr(seed_module, "seed", interrupted)
    with pytest.raises(KeyboardInterrupt):
        build_demo_database(target, NOW)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []  # 暫存檔也已清除

    monkeypatch.setattr(seed_module, "seed", real_seed)
    summary = build_demo_database(target, NOW)
    assert sum(summary.packages.values()) >= 50
    assert count(target, Package) == sum(summary.packages.values())


def test_rebuilding_demo_replaces_old_database(tmp_path):
    target = tmp_path / "demo.db"
    build_demo_database(target, NOW)
    build_demo_database(target, NOW)
    assert count(target, User) == 52  # 不是疊加成兩份


def test_insecure_secret_fails_before_touching_database(tmp_path, monkeypatch):
    db_file = tmp_path / "data" / "parcel_desk.db"
    monkeypatch.setenv("PARCEL_DATABASE_PATH", str(db_file))
    monkeypatch.setenv("PARCEL_JWT_SECRET", "dev-secret-change-me-in-production")
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as exc:
            main(["serve"])
    finally:
        get_settings.cache_clear()
    assert exc.value.code == 1
    assert not db_file.exists()
