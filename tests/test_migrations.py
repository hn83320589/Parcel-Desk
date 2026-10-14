from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from parcel_desk.db import run_migrations
from parcel_desk.models import Base


def test_upgrade_head_builds_database_from_scratch(tmp_path):
    db_path = tmp_path / "fresh.db"
    assert not db_path.exists()

    run_migrations(db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert set(Base.metadata.tables) <= tables


def test_migrations_match_models(db_path):
    """models 改了卻忘了寫 migration 時，這個測試會失敗。"""
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []
