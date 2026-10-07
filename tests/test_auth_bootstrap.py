"""初期 admin の作成、子プロセスへの秘密の受け渡し防止、期限切れセッションの掃除。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from vcenter_event_assistant.auth.bootstrap import BootstrapError, ensure_bootstrap_admin
from vcenter_event_assistant.auth.passwords import verify_password
from vcenter_event_assistant.auth.service import session_policy
from vcenter_event_assistant.auth.sessions import create_session
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.auth.users import count_users, create_local_user, get_local_user
from vcenter_event_assistant.db.models import AuthSession
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.jobs.scheduler import purge_retention
from vcenter_event_assistant.plugins.subprocess_env import child_process_env
from vcenter_event_assistant.settings import get_settings

BOOT_PASSWORD = "bootstrap long password"


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings()


async def test_creates_admin_once(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        monkeypatch,
        VEA_BOOTSTRAP_ADMIN_USERNAME="root",
        VEA_BOOTSTRAP_ADMIN_PASSWORD=BOOT_PASSWORD,
    )
    await ensure_bootstrap_admin(settings)
    await ensure_bootstrap_admin(settings)
    async with session_scope() as db:
        assert await count_users(db) == 1
        user = await get_local_user(db, "root")
        assert user is not None and user.role == "admin"
        assert (await verify_password(user.password_hash, BOOT_PASSWORD)).ok


async def test_does_not_override_existing_users(monkeypatch: pytest.MonkeyPatch) -> None:
    async with session_scope() as db:
        await create_local_user(
            db, username="existing", password="existing long pw", role="viewer", password_min_length=12
        )
    settings = _settings(
        monkeypatch,
        VEA_BOOTSTRAP_ADMIN_USERNAME="root",
        VEA_BOOTSTRAP_ADMIN_PASSWORD=BOOT_PASSWORD,
    )
    await ensure_bootstrap_admin(settings)
    async with session_scope() as db:
        assert await get_local_user(db, "root") is None


@pytest.mark.parametrize(
    "env",
    [
        {"VEA_BOOTSTRAP_ADMIN_USERNAME": "root", "VEA_BOOTSTRAP_ADMIN_PASSWORD": "short"},
        {"VEA_BOOTSTRAP_ADMIN_USERNAME": "root"},
        {"VEA_BOOTSTRAP_ADMIN_PASSWORD": BOOT_PASSWORD},
    ],
)
async def test_invalid_bootstrap_config_stops_startup(monkeypatch: pytest.MonkeyPatch, env) -> None:
    with pytest.raises(BootstrapError):
        await ensure_bootstrap_admin(_settings(monkeypatch, **env))


async def test_no_users_without_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    # 開発環境では警告だけ
    await ensure_bootstrap_admin(_settings(monkeypatch))
    # 本番で認証が有効なら起動を止める
    prod = _settings(
        monkeypatch,
        APP_ENV="production",
        VEA_SECRET_KEY="prod-secret-key",
        VCENTER_ALLOWED_HOST_SUFFIXES="example.com",
    )
    with pytest.raises(BootstrapError):
        await ensure_bootstrap_admin(prod)
    # 認証が無効なら何もしない
    await ensure_bootstrap_admin(_settings(monkeypatch, VEA_AUTH_ENABLED="false"))


def test_child_process_env_withholds_bootstrap_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEA_BOOTSTRAP_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SOME_OTHER_VAR", "kept")
    env = child_process_env()
    assert "VEA_BOOTSTRAP_ADMIN_PASSWORD" not in env
    assert env["SOME_OTHER_VAR"] == "kept"


async def test_purge_retention_removes_expired_sessions() -> None:
    settings = get_settings()
    now = utcnow()
    async with session_scope() as db:
        user = await create_local_user(
            db, username="sess", password="session long pw", role="viewer", password_min_length=12
        )
        await create_session(db, user, session_policy(settings), now=now - timedelta(days=2))
        await create_session(db, user, session_policy(settings), now=now)
    await purge_retention(settings)
    async with session_scope() as db:
        assert len((await db.scalars(select(AuthSession))).all()) == 1
