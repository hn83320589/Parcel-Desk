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
