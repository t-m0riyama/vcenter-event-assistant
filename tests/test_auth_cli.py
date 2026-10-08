"""ユーザー管理 CLI。"""

from __future__ import annotations

import asyncio
import io
from datetime import timedelta

import pytest
from sqlalchemy import update

from vcenter_event_assistant.auth import cli
from vcenter_event_assistant.auth.passwords import PasswordPolicyError, verify_password
from vcenter_event_assistant.auth.users import LastAdminError, get_local_user
from vcenter_event_assistant.auth.sessions import (
    SessionPolicy,
    create_session,
    resolve_session,
)
from vcenter_event_assistant.db.models import User
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.settings_binding import require_settings


async def _run(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], stdin: str = ""
) -> str:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return await cli.run(argv, settings=require_settings())


async def test_create_reset_role_unlock_list(monkeypatch: pytest.MonkeyPatch) -> None:
    out = await _run(
        monkeypatch,
        ["create-user", "root", "--role", "admin", "--password-stdin"],
        "first long password\n",
    )
    assert "root" in out
    await _run(
        monkeypatch,
        ["create-user", "ops", "--role", "operator", "--password-stdin"],
        "ops long password\n",
    )

    async with session_scope() as db:
        user = await get_local_user(db, "root")
        assert user is not None and user.role == "admin"
        user.failed_login_count = 5
        user.is_active = False

    await _run(
        monkeypatch,
        ["reset-password", "root", "--password-stdin"],
        "second long password\n",
    )
    await _run(monkeypatch, ["unlock", "root"])
    async with session_scope() as db:
        user = await get_local_user(db, "root")
        assert user is not None
        assert user.is_active and user.failed_login_count == 0
        assert (await verify_password(user.password_hash, "second long password")).ok

    await _run(monkeypatch, ["set-role", "ops", "viewer"])
    listing = await _run(monkeypatch, ["list-users"])
    assert "root" in listing and "viewer" in listing


async def test_unlock_reactivation_revokes_old_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _run(
        monkeypatch, ["create-user", "back", "--password-stdin"], "back long password\n"
    )
    policy = SessionPolicy(
        idle_timeout=timedelta(hours=1), absolute_timeout=timedelta(hours=12)
    )
    async with session_scope() as db:
        user = await get_local_user(db, "back")
        assert user is not None
        token = await create_session(db, user, policy)
        # セッションを残したまま無効化された状態（DB の直接操作などを想定）
        await db.execute(update(User).where(User.id == user.id).values(is_active=False))
    await _run(monkeypatch, ["unlock", "back"])
    async with session_scope() as db:
        assert await resolve_session(db, token, policy) is None
        user = await get_local_user(db, "back")
        assert user is not None and user.is_active


async def test_cannot_demote_last_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    await _run(
        monkeypatch,
        ["create-user", "solo", "--role", "admin", "--password-stdin"],
        "solo long password\n",
    )
    with pytest.raises(LastAdminError):
        await _run(monkeypatch, ["set-role", "solo", "viewer"])


async def test_concurrent_demotion_keeps_one_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2 人の admin を同時に降格しても、有効な admin が 0 人にならない。"""
    for name in ("adm1", "adm2"):
        await _run(
            monkeypatch,
            ["create-user", name, "--role", "admin", "--password-stdin"],
            f"{name} long password\n",
        )
    results = await asyncio.gather(
        _run(monkeypatch, ["set-role", "adm1", "viewer"]),
        _run(monkeypatch, ["set-role", "adm2", "viewer"]),
        return_exceptions=True,
    )
    assert sum(isinstance(r, LastAdminError) for r in results) == 1, results
    async with session_scope() as db:
        roles = {
            name: (await get_local_user(db, name)).role for name in ("adm1", "adm2")
        }
    assert sorted(roles.values()) == ["admin", "viewer"]


async def test_create_user_rejects_weak_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(PasswordPolicyError):
        await _run(monkeypatch, ["create-user", "weak", "--password-stdin"], "short\n")


def test_main_prints_error_and_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    async def failing_run(argv):
        raise cli.CliError("boom")

    monkeypatch.setattr(cli, "run", failing_run)
    assert cli.main(["list-users"]) == 1
    assert "エラー: boom" in capsys.readouterr().err
