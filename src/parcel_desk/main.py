from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from parcel_desk.api import auth, units, users
from parcel_desk.clock import Clock, SystemClock
from parcel_desk.config import Settings, get_settings
from parcel_desk.db import make_engine, make_session_factory
from parcel_desk.errors import DomainError, domain_error_handler


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
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
    app.state.clock = clock or SystemClock()
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    app.add_exception_handler(DomainError, domain_error_handler)
    for module in (auth, units, users):
        app.include_router(module.router)
    return app
