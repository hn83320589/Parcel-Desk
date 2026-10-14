import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from parcel_desk.clock import FixedClock
from parcel_desk.db import make_engine, make_session_factory, run_migrations

# 2026-10-01 10:00 台北時間
START = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def template_db(tmp_path_factory) -> Path:
    """整個測試階段只跑一次 alembic upgrade head，之後每個測試複製一份檔案。"""
    path = tmp_path_factory.mktemp("template") / "template.db"
    run_migrations(path)
    return path


@pytest.fixture
def db_path(template_db: Path, tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    shutil.copy(template_db, path)
    return path


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


@pytest.fixture
def session(db_path: Path):
    engine = make_engine(db_path)
    factory = make_session_factory(engine)
    with factory() as s:
        yield s
    engine.dispose()


# ---- API 層 fixtures ----------------------------------------------------------

from dataclasses import dataclass, field  # noqa: E402
from datetime import timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from parcel_desk import security  # noqa: E402
from parcel_desk.config import Settings  # noqa: E402
from parcel_desk.main import create_app  # noqa: E402
from parcel_desk.models import Role, User  # noqa: E402
from parcel_desk.services.units import create_unit  # noqa: E402
from parcel_desk.services.users import create_user  # noqa: E402

TEST_SECRET = "test-secret-that-is-at-least-32-bytes-long"


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def app(db_path, clock):
    settings = Settings(database_path=db_path, scheduler_enabled=False, jwt_secret=TEST_SECRET)
    return create_app(settings, clock=clock)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(app):
    """與 API 共用同一個資料庫檔案的 session，用來準備資料與檢查結果。"""
    with app.state.session_factory() as s:
        yield s


@dataclass
class World:
    """常用的測試資料：兩戶、各自的住戶、管委會與兩位管理員。"""

    db: object
    clock: FixedClock
    secret: str
    users: dict[str, User] = field(default_factory=dict)

    def headers(self, username: str) -> dict[str, str]:
        user = self.users[username]
        token = security.create_access_token(
            user.id, user.role.value, self.secret, datetime.now(UTC), timedelta(hours=1)
        )
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def world(db, clock) -> World:
    now = clock.now()
    for code in ("A-12F-3", "B-5F-1"):
        create_unit(db, code, now)
    w = World(db=db, clock=clock, secret=TEST_SECRET)
    specs = [
        ("admin", Role.ADMIN, None),
        ("staff_a", Role.STAFF, None),
        ("staff_b", Role.STAFF, None),
        ("alice", Role.RESIDENT, "A-12F-3"),
        ("amy", Role.RESIDENT, "A-12F-3"),
        ("bob", Role.RESIDENT, "B-5F-1"),
    ]
    for username, role, unit_code in specs:
        w.users[username] = create_user(
            db,
            username=username,
            password="password123",
            display_name=username.title(),
            role=role,
            unit_code=unit_code,
            now=now,
        )
    return w
