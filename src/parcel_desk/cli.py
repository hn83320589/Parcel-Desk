"""`parcel-desk` 指令。

parcel-desk                正式模式：升級資料庫 → 首次啟動建立 admin（一次性密碼）→ 啟動 API
parcel-desk demo           示範模式：使用獨立的示範資料庫並載入 seed → 啟動 API
parcel-desk demo --reset   重建示範資料庫後啟動
parcel-desk migrate        只對正式資料庫執行 alembic upgrade head
"""

import argparse
import logging

import uvicorn

from parcel_desk.clock import SystemClock
from parcel_desk.config import Settings, get_settings
from parcel_desk.db import make_engine, make_session_factory, run_migrations
from parcel_desk.security import InsecureSecretError, resolve_jwt_secret
from parcel_desk.seed import build_demo_database
from parcel_desk.services.users import BOOTSTRAP_ADMIN_USERNAME, bootstrap_admin

logger = logging.getLogger("parcel_desk")


def prepare_production(settings: Settings) -> str | None:
    """升級正式資料庫；沒有任何帳號時建立 admin 並回傳一次性密碼。永不載入示範資料。"""
    run_migrations(settings.database_path)
    engine = make_engine(settings.database_path)
    try:
        with make_session_factory(engine)() as session:
            return bootstrap_admin(session, SystemClock().now())
    finally:
        engine.dispose()


def prepare_demo(settings: Settings, reset: bool) -> None:
    path = settings.database_path
    if reset or not path.exists():
        logger.info("建立示範資料庫 %s（約需 10–20 秒）…", path)
        summary = build_demo_database(path, SystemClock().now())
        logger.info("示範資料庫已建立：%s", summary)
    else:
        run_migrations(path)
        logger.info("沿用既有示範資料庫 %s（加上 --reset 可重建）", path)


def _print_bootstrap_password(password: str) -> None:
    line = "=" * 60
    print(
        f"\n{line}\n"
        f"  首次啟動：已建立管委會帳號\n"
        f"    帳號：{BOOTSTRAP_ADMIN_USERNAME}\n"
        f"    密碼：{password}\n"
        f"  此密碼只會顯示這一次。登入後必須先呼叫\n"
        f"  POST /auth/change-password 修改密碼，才能使用其他功能。\n"
        f"{line}\n",
        flush=True,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="parcel-desk", description="社區包裹代收系統")
    sub = parser.add_subparsers(dest="command")
    for name, help_text in (("serve", "正式模式啟動 API（預設）"), ("demo", "示範模式啟動 API")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--host")
        cmd.add_argument("--port", type=int)
        if name == "demo":
            cmd.add_argument("--reset", action="store_true", help="重建示範資料庫")
    sub.add_parser("migrate", help="對正式資料庫執行 alembic upgrade head")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()

    if args.command == "migrate":
        run_migrations(settings.database_path)
        logger.info("資料庫已升級至最新版本：%s", settings.database_path)
        return

    demo = args.command == "demo"
    if demo:
        settings = settings.model_copy(update={"database_path": settings.demo_database_path})

    # 在碰資料庫之前先檢查密鑰，設定錯誤時立即停止
    try:
        resolve_jwt_secret(settings.jwt_secret, settings.jwt_secret_file)
    except InsecureSecretError as exc:
        logger.error("無法啟動：%s", exc)
        raise SystemExit(1) from exc

    if demo:
        prepare_demo(settings, reset=args.reset)
    else:
        password = prepare_production(settings)
        if password is not None:
            _print_bootstrap_password(password)

    from parcel_desk.main import create_app

    host = getattr(args, "host", None) or settings.host
    port = getattr(args, "port", None) or settings.port
    logger.info("%s模式，Swagger UI：http://localhost:%d/docs", "示範" if demo else "正式", port)
    uvicorn.run(create_app(settings), host=host, port=port)


if __name__ == "__main__":
    main()
