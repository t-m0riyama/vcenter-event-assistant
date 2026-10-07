"""起動時の初期 admin 作成。

ユーザーが 1 人もいないときだけ、``VEA_BOOTSTRAP_ADMIN_USERNAME`` /
``VEA_BOOTSTRAP_ADMIN_PASSWORD`` からローカル admin を作る。2 回目以降の起動では何もしない。
"""

from __future__ import annotations

import logging

from vcenter_event_assistant.auth.audit import audit
from vcenter_event_assistant.auth.passwords import PasswordPolicyError
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.auth.users import UserError, count_users, create_local_user
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)


class BootstrapError(RuntimeError):
    """初期 admin を用意できず、起動を続けられない。"""


async def ensure_bootstrap_admin(settings: Settings) -> None:
    username = settings.bootstrap_admin_username
    password = (
        settings.bootstrap_admin_password.get_secret_value()
        if settings.bootstrap_admin_password is not None
        else None
    )
    async with session_scope(settings) as db:
        if await count_users(db) > 0:
            if password:
                logger.warning(
                    "VEA_BOOTSTRAP_ADMIN_PASSWORD is set but users already exist; it is ignored. "
                    "Remove it from the environment."
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

    if not settings.auth_enabled:
        return
    message = (
        "認証が有効ですがユーザーが 1 人もいません。VEA_BOOTSTRAP_ADMIN_USERNAME / "
        "VEA_BOOTSTRAP_ADMIN_PASSWORD を設定するか、vcenter-event-assistant-admin create-user "
        "で admin を作成してください。"
    )
    if settings.is_production:
        raise BootstrapError(message)
    logger.warning(message)
