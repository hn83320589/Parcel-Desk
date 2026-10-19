"""JWT 密鑰不可有公開的預設值：任何看過 repo 的人都不能偽造 token。"""

import os
import stat
import sys
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from parcel_desk.config import Settings
from parcel_desk.main import create_app
from parcel_desk.security import (
    KNOWN_INSECURE_SECRETS,
    InsecureSecretError,
    resolve_jwt_secret,
)

LEAKED_DEFAULT = "dev-secret-change-me-in-production"


def test_generates_secret_file_when_not_configured(tmp_path):
    secret_file = tmp_path / ".jwt_secret"

    secret = resolve_jwt_secret(None, secret_file)

    assert len(secret) >= 32
    assert secret_file.read_text().strip() == secret
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(secret_file).st_mode) == 0o600


def test_reuses_existing_secret_file_so_logins_survive_restart(tmp_path):
    secret_file = tmp_path / ".jwt_secret"
    first = resolve_jwt_secret(None, secret_file)
    assert resolve_jwt_secret(None, secret_file) == first


def test_secret_files_differ_between_installations(tmp_path):
    a = resolve_jwt_secret(None, tmp_path / "a" / ".jwt_secret")
    b = resolve_jwt_secret(None, tmp_path / "b" / ".jwt_secret")
    assert a != b


@pytest.mark.parametrize("bad", ["too-short", LEAKED_DEFAULT])
def test_rejects_short_or_publicly_known_secret(tmp_path, bad):
    with pytest.raises(InsecureSecretError):
        resolve_jwt_secret(bad, tmp_path / ".jwt_secret")


def test_leaked_default_is_in_blocklist():
    assert LEAKED_DEFAULT in KNOWN_INSECURE_SECRETS


def test_token_forged_with_leaked_default_is_rejected(tmp_path, clock):
    """重現 review 中的攻擊：用 repo 曾公開的預設密鑰簽 admin token。"""
    from parcel_desk.db import run_migrations

    run_migrations(tmp_path / "app.db")
    settings = Settings(database_path=tmp_path / "app.db", scheduler_enabled=False)
    app = create_app(settings, clock=clock)
    now = datetime.now(UTC)
    forged = jwt.encode(
        {"sub": "1", "exp": now + timedelta(hours=1)}, LEAKED_DEFAULT, algorithm="HS256"
    )
    with TestClient(app) as client:
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


def test_concurrent_first_start_reads_the_file_created_by_the_other_process(tmp_path, monkeypatch):
    """兩個程序同時首次啟動：exists() 都回 False，後到的 O_EXCL 失敗時改讀既有檔案。"""
    from pathlib import Path

    secret_file = tmp_path / ".jwt_secret"
    secret_file.write_text("x" * 64)  # 另一個程序剛建立好
    monkeypatch.setattr(Path, "exists", lambda self: False)

    assert resolve_jwt_secret(None, secret_file) == "x" * 64


@pytest.mark.parametrize("content", ["", "short"])
def test_rejects_empty_or_short_secret_file(tmp_path, content):
    secret_file = tmp_path / ".jwt_secret"
    secret_file.write_text(content)
    with pytest.raises(InsecureSecretError):
        resolve_jwt_secret(None, secret_file)
