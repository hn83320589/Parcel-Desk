from fastapi.testclient import TestClient

from parcel_desk.config import Settings
from parcel_desk.main import create_app
from parcel_desk.scheduler import JOB_ID


def test_scheduler_registers_reminder_job_on_startup(db_path, clock):
    settings = Settings(database_path=db_path, scheduler_enabled=True, reminder_interval_minutes=10)
    app = create_app(settings, clock=clock)
    with TestClient(app):
        job = app.state.scheduler.get_job(JOB_ID)
        assert job is not None
        assert job.trigger.interval.total_seconds() == 600
    assert not app.state.scheduler.running
