"""ユーザー管理 CLI（``vcenter-event-assistant-admin``）。

初期 admin の作成や、ログインできなくなったときの復旧に使う。
パスワードはコマンドライン引数では受け取らない（プロセス一覧やシェル履歴に残るため）。
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence

from sqlalchemy import select

from vcenter_event_assistant.auth.passwords import PasswordPolicyError
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.auth.sessions import revoke_all_for_user
from vcenter_event_assistant.auth.users import (
    UserError,
    admin_change_guard,
    create_local_user,
    ensure_not_last_admin,
    get_local_user,
    set_local_password,
    unlock_user,
)
from vcenter_event_assistant.db.models import User
from vcenter_event_assistant.db.session import init_db, session_scope
from vcenter_event_assistant.settings import Settings, get_settings
from vcenter_event_assistant.settings_binding import bind_settings


class CliError(Exception):
    pass


def _read_password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        value = sys.stdin.readline().rstrip("\r\n")
        if not value:
            raise CliError("標準入力からパスワードを読み取れませんでした。")
        return value
    first = getpass.getpass("パスワード: ")
    second = getpass.getpass("パスワード（確認）: ")
    if first != second:
        raise CliError("パスワードが一致しません。")
    return first


async def _get_user_or_fail(db, username: str) -> User:
    user = await get_local_user(db, username)
    if user is None:
        raise CliError(f"ローカルユーザー '{username}' が見つかりません。")
    return user


async def _create_user(settings: Settings, args: argparse.Namespace) -> str:
    password = _read_password(args)
    async with session_scope(settings) as db:
        user = await create_local_user(
            db,
            username=args.username,
            password=password,
            role=args.role,
            password_min_length=settings.password_min_length,
            display_name=args.display_name,
            email=args.email,
        )
        return f"ユーザー '{user.username}'（{user.role}）を作成しました。"


async def _reset_password(settings: Settings, args: argparse.Namespace) -> str:
    password = _read_password(args)
    async with session_scope(settings) as db:
        user = await _get_user_or_fail(db, args.username)
        await set_local_password(db, user, password, password_min_length=settings.password_min_length)
        return f"ユーザー '{user.username}' のパスワードを変更し、ロックを解除しました。"


async def _set_role(settings: Settings, args: argparse.Namespace) -> str:
    async with session_scope(settings) as db, admin_change_guard(db):
        user = await _get_user_or_fail(db, args.username)
        if args.role != Role.ADMIN.value:
            await ensure_not_last_admin(db, user)
        user.role = Role(args.role).value
        await revoke_all_for_user(db, user.id)
        return f"ユーザー '{user.username}' のロールを {user.role} にしました。"


async def _unlock(settings: Settings, args: argparse.Namespace) -> str:
    async with session_scope(settings) as db:
        user = await _get_user_or_fail(db, args.username)
        unlock_user(user)
        if not user.is_active:
            # 無効化前のセッション（盗まれたものを含む）を有効化で復活させない
            await revoke_all_for_user(db, user.id)
            user.is_active = True
        return f"ユーザー '{user.username}' のロックを解除し、有効にしました。"


async def _list_users(settings: Settings, _args: argparse.Namespace) -> str:
    async with session_scope(settings) as db:
        rows = (await db.scalars(select(User).order_by(User.realm_key, User.username))).all()
    if not rows:
        return "ユーザーはいません。"
    lines = [f"{'USERNAME':<32} {'REALM':<44} {'ROLE':<9} ACTIVE"]
    for u in rows:
        lines.append(f"{u.username:<32} {u.realm_key:<44} {u.role:<9} {'yes' if u.is_active else 'no'}")
    return "\n".join(lines)


_COMMANDS = {
    "create-user": _create_user,
    "reset-password": _reset_password,
    "set-role": _set_role,
    "unlock": _unlock,
    "list-users": _list_users,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vcenter-event-assistant-admin",
        description="vCenter Event Assistant のローカルユーザーを管理します。",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    roles = [r.value for r in Role]

    p = sub.add_parser("create-user", help="ローカルユーザーを作成する")
    p.add_argument("username")
    p.add_argument("--role", choices=roles, default=Role.VIEWER.value)
    p.add_argument("--display-name")
    p.add_argument("--email")
    p.add_argument("--password-stdin", action="store_true", help="パスワードを標準入力の 1 行目から読む")

    p = sub.add_parser("reset-password", help="ローカルユーザーのパスワードを再設定する")
    p.add_argument("username")
    p.add_argument("--password-stdin", action="store_true", help="パスワードを標準入力の 1 行目から読む")

    p = sub.add_parser("set-role", help="ローカルユーザーのロールを変更する")
    p.add_argument("username")
    p.add_argument("role", choices=roles)

    p = sub.add_parser("unlock", help="ロックを解除してユーザーを有効にする")
    p.add_argument("username")

    sub.add_parser("list-users", help="ユーザーの一覧を表示する")
    return parser


async def run(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> str:
    args = build_parser().parse_args(argv)
    s = settings or get_settings()
    bind_settings(s)
    await init_db(settings=s)
    return await _COMMANDS[args.command](s, args)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        message = asyncio.run(run(argv))
    except (CliError, UserError, PasswordPolicyError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
