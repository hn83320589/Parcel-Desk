from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from parcel_desk.api import (
    admin,
    auth,
    notifications,
    packages,
    proxies,
    reports,
    units,
    users,
)
from parcel_desk.clock import Clock, SystemClock
from parcel_desk.config import Settings, get_settings
from parcel_desk.db import make_engine, make_session_factory
from parcel_desk.errors import DomainError, domain_error_handler
from parcel_desk.scheduler import start_scheduler
from parcel_desk.security import resolve_jwt_secret


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = None
        if settings.scheduler_enabled:
            scheduler = start_scheduler(
                app.state.session_factory, app.state.clock, settings.reminder_interval_minutes
            )
        app.state.scheduler = scheduler
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        app.state.engine.dispose()

    app = FastAPI(
        title="Parcel Desk 社區包裹代收系統",
        version="0.1.0",
        description=(
            "以右上角 Authorize 登入（seed 帳號見 README）。所有時間以台北時間（+08:00）呈現。"
        ),
        lifespan=lifespan,
    )
    engine = make_engine(settings.database_path)
    app.state.settings = settings
    app.state.jwt_secret = resolve_jwt_secret(settings.jwt_secret, settings.jwt_secret_file)
    app.state.clock = clock or SystemClock()
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    app.add_exception_handler(DomainError, domain_error_handler)
    for module in (auth, units, users, proxies, packages, notifications, reports, admin):
        app.include_router(module.router)
    return app
