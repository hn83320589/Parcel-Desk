"""示範模式簽發的 token 絕不能在正式模式使用。

兩層防護：
1. 密鑰檔依資料庫各自存放（parcel_desk.db.jwt_secret / demo.db.jwt_secret）。
2. token 的 aud 綁定資料庫的安裝識別碼；即使兩邊用同一把 PARCEL_JWT_SECRET 也無法互通。
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from parcel_desk.cli import prepare_production
from parcel_desk.config import Settings
from parcel_desk.db import make_engine, make_session_factory
from parcel_desk.main import create_app
from parcel_desk.seed import build_demo_database
from parcel_desk.services.installation import get_installation_id
from tests.conftest import TEST_SECRET

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)


def installation_id(db_path) -> str:
    engine = make_engine(db_path)
    try:
        with make_session_factory(engine)() as s:
            return get_installation_id(s)
    finally:
        engine.dispose()


@pytest.fixture
def same_dir_settings(tmp_path):
    """與預設配置相同：正式與示範資料庫放在同一個 data/ 目錄。"""
    data = tmp_path / "data"

    def make(jwt_secret=None):
        prod = Settings(
            database_path=data / "parcel_desk.db", scheduler_enabled=False, jwt_secret=jwt_secret
        )
        demo = prod.model_copy(update={"database_path": data / "demo.db"})
        return prod, demo

    return make


def demo_admin_token(demo_settings, clock) -> str:
    build_demo_database(demo_settings.database_path, NOW)
    with TestClient(create_app(demo_settings, clock=clock)) as c:
        resp = c.post("/auth/token", data={"username": "admin", "password": "admin1234"})
        assert resp.status_code == 200
        return resp.json()["access_token"]


def test_secret_files_are_per_database(same_dir_settings):
    prod, demo = same_dir_settings()
    assert prod.jwt_secret_file != demo.jwt_secret_file
    assert prod.jwt_secret_file.parent == demo.jwt_secret_file.parent
    assert prod.jwt_secret_file.name == "parcel_desk.db.jwt_secret"


def test_demo_token_is_rejected_by_production(same_dir_settings, clock):
    """重現 review：示範模式 admin/admin1234 的 token 打正式模式。"""
    prod, demo = same_dir_settings()
    token = demo_admin_token(demo, clock)
    prepare_production(prod)

    with TestClient(create_app(prod, clock=clock)) as c:
        h = {"Authorization": f"Bearer {token}"}
        assert c.get("/auth/me", headers=h).status_code == 401
        assert c.get("/reports/monthly?month=2026-10", headers=h).status_code == 401


def test_shared_env_secret_is_still_isolated_by_audience(same_dir_settings, clock):
    """即使兩種模式都設定同一把 PARCEL_JWT_SECRET，token 仍無法互通。"""
    prod, demo = same_dir_settings(jwt_secret=TEST_SECRET)
    token = demo_admin_token(demo, clock)
    prepare_production(prod)

    with TestClient(create_app(prod, clock=clock)) as c:
        assert c.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_token_without_audience_is_rejected(app, client, world):
    """升級前簽發、沒有 aud 的 token 一律失效。"""
    admin = world.users["admin"]
    legacy = jwt.encode(
        {"sub": str(admin.id), "exp": datetime.now(UTC) + timedelta(hours=1)},
        TEST_SECRET,
        algorithm="HS256",
    )
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 401
    assert client.get("/auth/me", headers=world.headers("admin")).status_code == 200


def test_installation_id_is_stable_per_database_and_differs_between_databases(tmp_path):
    from parcel_desk.db import run_migrations

    a, b = tmp_path / "a.db", tmp_path / "b.db"
    run_migrations(a)
    run_migrations(b)
    first = installation_id(a)
    assert installation_id(a) == first  # 重啟後沿用
    assert installation_id(b) != first
