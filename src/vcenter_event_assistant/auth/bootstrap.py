"""起動時の初期 admin 作成。

ユーザーが 1 人もいないときだけ、``VEA_BOOTSTRAP_ADMIN_USERNAME`` /
``VEA_BOOTSTRAP_ADMIN_PASSWORD`` からローカル admin を作る。2 回目以降の起動では何もしない。
"""

from __future__ import annotations

import logging

from vcenter_event_assistant.auth.audit import audit
from vcenter_event_assistant.auth.passwords import PasswordPolicyError
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.auth.users import (
    DuplicateUserError,
    UserError,
    count_active_admins,
    count_users,
    create_local_user,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)


class BootstrapError(RuntimeError):
    """初期 admin を用意できず、起動を続けられない。"""


async def ensure_bootstrap_admin(settings: Settings) -> None:
    try:
        await _ensure_bootstrap_admin(settings)
    except DuplicateUserError:
        # 同時に起動した別のワーカーなどが、先に同名ユーザーを作っていた。それが admin とは
        # 限らない（CLI で viewer として作られた等）ので、有効な admin が実在するかを確かめ直す
        async with session_scope(settings) as db:
            admins = await count_active_admins(db)
        if admins == 0:
            _report_missing_admin(
                settings,
                "初期 admin と同名のユーザーが別の操作で先に作られ、有効な admin がいません。"
                "vcenter-event-assistant-admin set-role <ユーザー名> admin で昇格してください。",
            )
            return
        logger.info("Initial admin user was created by another process.")


async def _ensure_bootstrap_admin(settings: Settings) -> None:
    username = settings.bootstrap_admin_username
    password = (
        settings.bootstrap_admin_password.get_secret_value()
        if settings.bootstrap_admin_password is not None
        else None
    )
    if not settings.auth_enabled:
        # 認証が無効なら初期 admin は使われない。不完全な設定が残っていても起動は止めず、
        # 使われないアカウントも作らない（認証を有効にした次の起動で作る）
        if username or password:
            logger.warning("VEA_BOOTSTRAP_ADMIN_* is ignored because VEA_AUTH_ENABLED=false.")
        return
    if not settings.local_login_enabled:
        # 初期 admin はローカルユーザーなので、ローカルログインが無効だと誰も管理できない
        if username or password:
            raise BootstrapError(
                "VEA_LOCAL_LOGIN_ENABLED=false のため、VEA_BOOTSTRAP_ADMIN_* で作るローカルの"
                "初期 admin ではログインできません。ローカルログインを有効にしてください。"
            )
        # 現時点でログインできる認証先はローカルだけ
        # （AD / LDAP を追加したら、有効なディレクトリがあるかもここで判定する）
        _report_missing_admin(
            settings,
            "認証が有効ですが、ログインできる認証先がありません（VEA_LOCAL_LOGIN_ENABLED=false）。"
            "ローカルログインを有効にしてください。",
        )
        return
    async with session_scope(settings) as db:
        if await count_users(db) > 0:
            if password:
                logger.warning(
                    "VEA_BOOTSTRAP_ADMIN_PASSWORD is set but users already exist; it is ignored. "
                    "Remove it from the environment."
                )
            if await count_active_admins(db) == 0:
                # 例: CLI の create-user を既定ロール（viewer）で実行しただけの状態
                _report_missing_admin(
                    settings,
                    "認証が有効ですが有効な admin がいません。"
                    "vcenter-event-assistant-admin set-role <ユーザー名> admin で既存ユーザーを昇格するか、"
                    "vcenter-event-assistant-admin create-user <ユーザー名> --role admin で作成してください。",
                )
            return

        if username and password:
            try:
                user = await create_local_user(
                    db,
                    username=username,
                    password=password,
                    role=Role.ADMIN,
                    password_min_length=settings.password_min_length,
                )
            except DuplicateUserError:
                raise
            except (PasswordPolicyError, UserError) as exc:
                raise BootstrapError(
                    f"初期 admin を作成できません（VEA_BOOTSTRAP_ADMIN_*）: {exc}"
                ) from None
            audit("bootstrap_admin_created", username=user.username)
            logger.warning(
                "Created initial admin user %r. Remove VEA_BOOTSTRAP_ADMIN_PASSWORD from the "
                "environment after the first login.",
                user.username,
            )
            return

        if username or password:
            raise BootstrapError(
                "VEA_BOOTSTRAP_ADMIN_USERNAME と VEA_BOOTSTRAP_ADMIN_PASSWORD は両方設定してください。"
            )

    _report_missing_admin(
        settings,
        "認証が有効ですがユーザーが 1 人もいません。VEA_BOOTSTRAP_ADMIN_USERNAME / "
        "VEA_BOOTSTRAP_ADMIN_PASSWORD を設定するか、"
        "vcenter-event-assistant-admin create-user <ユーザー名> --role admin で作成してください。",
    )


def _report_missing_admin(settings: Settings, message: str) -> None:
    """認証が有効なのにログインできる admin がいない。本番では起動を止め、開発環境では警告だけ出す。"""
    if not settings.auth_enabled:
        return
    if settings.is_production:
        raise BootstrapError(message)
    logger.warning(message)
