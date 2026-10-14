"""`parcel-desk` 指令。

parcel-desk              建立/升級資料庫 → 空資料庫時載入 seed → 啟動 API（預設）
parcel-desk migrate      只執行 alembic upgrade head
parcel-desk seed --reset 刪除資料庫後重建並載入 seed
"""

import argparse
import logging

import uvicorn

from parcel_desk.clock import SystemClock
from parcel_desk.config import Settings, get_settings
from parcel_desk.db import make_engine, make_session_factory, run_migrations
from parcel_desk.seed import seed_if_empty

logger = logging.getLogger("parcel_desk")


def _prepare_database(settings: Settings) -> None:
    run_migrations(settings.database_path)
    engine = make_engine(settings.database_path)
    try:
        summary = seed_if_empty(make_session_factory(engine), SystemClock().now())
    finally:
        engine.dispose()
    if summary is None:
        logger.info("資料庫已有資料，略過 seed")
    else:
        logger.info("已載入 seed：%s", summary)


def _reset_database(settings: Settings) -> None:
    for suffix in ("", "-wal", "-shm"):
        path = settings.database_path.with_name(settings.database_path.name + suffix)
        path.unlink(missing_ok=True)
    logger.info("已刪除資料庫 %s", settings.database_path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="parcel-desk", description="社區包裹代收系統")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="啟動 API（預設）")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    sub.add_parser("migrate", help="執行 alembic upgrade head")
    seed = sub.add_parser("seed", help="載入 seed 資料（資料庫為空時）")
    seed.add_argument("--reset", action="store_true", help="先刪除資料庫再重建")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()

    if args.command == "migrate":
        run_migrations(settings.database_path)
        logger.info("資料庫已升級至最新版本：%s", settings.database_path)
        return
    if args.command == "seed":
        if args.reset:
            _reset_database(settings)
        _prepare_database(settings)
        return

    _prepare_database(settings)
    from parcel_desk.main import create_app

    host = getattr(args, "host", None) or settings.host
    port = getattr(args, "port", None) or settings.port
    logger.info("Swagger UI：http://localhost:%d/docs", port)
    uvicorn.run(create_app(settings), host=host, port=port)


if __name__ == "__main__":
    main()
