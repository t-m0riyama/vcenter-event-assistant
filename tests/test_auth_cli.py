"""ユーザー管理 CLI。"""

from __future__ import annotations

import io

import pytest

from vcenter_event_assistant.auth import cli
from vcenter_event_assistant.auth.passwords import PasswordPolicyError, verify_password
from vcenter_event_assistant.auth.users import LastAdminError, get_local_user
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.settings_binding import require_settings


async def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str], stdin: str = "") -> str:
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
        monkeypatch, ["create-user", "ops", "--role", "operator", "--password-stdin"],
        "ops long password\n",
    )

    async with session_scope() as db:
        user = await get_local_user(db, "root")
        assert user is not None and user.role == "admin"
        user.failed_login_count = 5
        user.is_active = False

    await _run(monkeypatch, ["reset-password", "root", "--password-stdin"], "second long password\n")
    await _run(monkeypatch, ["unlock", "root"])
    async with session_scope() as db:
        user = await get_local_user(db, "root")
        assert user is not None
        assert user.is_active and user.failed_login_count == 0
        assert (await verify_password(user.password_hash, "second long password")).ok

    await _run(monkeypatch, ["set-role", "ops", "viewer"])
    listing = await _run(monkeypatch, ["list-users"])
    assert "root" in listing and "viewer" in listing


async def test_cannot_demote_last_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    await _run(
        monkeypatch, ["create-user", "solo", "--role", "admin", "--password-stdin"],
        "solo long password\n",
    )
    with pytest.raises(LastAdminError):
        await _run(monkeypatch, ["set-role", "solo", "viewer"])


async def test_create_user_rejects_weak_password(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(PasswordPolicyError):
        await _run(monkeypatch, ["create-user", "weak", "--password-stdin"], "short\n")


def test_main_prints_error_and_returns_nonzero(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    async def failing_run(argv):
        raise cli.CliError("boom")

    monkeypatch.setattr(cli, "run", failing_run)
    assert cli.main(["list-users"]) == 1
    assert "エラー: boom" in capsys.readouterr().err
