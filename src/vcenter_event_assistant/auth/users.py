"""ローカルユーザーの作成・パスワード変更など（CLI と API で共用）。"""

from __future__ import annotations

import unicodedata
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.auth.passwords import (
    hash_password,
    validate_password_policy,
)
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.auth.sessions import revoke_all_for_user
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.db.models import User

LOCAL_REALM = "local"
USERNAME_MAX_LENGTH = 256


class UserError(ValueError):
    """ユーザー操作の入力エラー（日本語メッセージ）。"""


def normalize_username(username: str) -> str:
    """前後の空白を除き NFKC 正規化する。空・制御文字・長すぎる値は拒否。"""
    value = unicodedata.normalize("NFKC", username).strip()
    if not value:
        raise UserError("ユーザー名を入力してください。")
    if len(value) > USERNAME_MAX_LENGTH:
        raise UserError(f"ユーザー名は {USERNAME_MAX_LENGTH} 文字以下にしてください。")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise UserError("ユーザー名に制御文字は使えません。")
    return value


def local_subject(username: str) -> str:
    return normalize_username(username).casefold()


async def get_local_user(db: AsyncSession, username: str) -> User | None:
    return await db.scalar(
        select(User).where(User.realm_key == LOCAL_REALM, User.subject == local_subject(username))
    )


async def count_users(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(User)) or 0)


async def count_active_admins(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == Role.ADMIN.value, User.is_active.is_(True))
        )
        or 0
    )


async def create_local_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    role: Role | str,
    password_min_length: int,
    display_name: str | None = None,
    email: str | None = None,
) -> User:
    name = normalize_username(username)
    validate_password_policy(password, min_length=password_min_length)
    if await get_local_user(db, name) is not None:
        raise UserError("同じユーザー名のローカルユーザーが既に存在します。")
    now = utcnow()
    user = User(
        realm_key=LOCAL_REALM,
        subject=name.casefold(),
        username=name,
        display_name=display_name,
        email=email,
        password_hash=await hash_password(password),
        role=Role(role).value,
        is_active=True,
        failed_login_count=0,
        password_changed_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.flush()
    return user


async def set_local_password(
    db: AsyncSession,
    user: User,
    password: str,
    *,
    password_min_length: int,
    keep_session_id: uuid.UUID | None = None,
) -> None:
    """パスワードを変更し、ロックを解除して他のセッションを全部失効させる。"""
    if user.realm_key != LOCAL_REALM:
        raise UserError("ディレクトリ由来のユーザーのパスワードは変更できません。")
    validate_password_policy(password, min_length=password_min_length)
    user.password_hash = await hash_password(password)
    user.password_changed_at = utcnow()
    user.failed_login_count = 0
    user.locked_until = None
    await revoke_all_for_user(db, user.id, except_session_id=keep_session_id)
    await db.flush()


def unlock_user(user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None
