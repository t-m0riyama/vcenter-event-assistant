"""ローカルユーザーの作成・パスワード変更など（CLI と API で共用）。"""

from __future__ import annotations

import asyncio
import unicodedata
import uuid
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.auth.passwords import (
    hash_password,
    validate_password_policy,
)
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.auth.sessions import credential_marker, revoke_all_for_user
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.db.models import AuthSession, User

LOCAL_REALM = "local"
USERNAME_MAX_LENGTH = 256
# User.display_name / User.email の列長
DISPLAY_NAME_MAX_LENGTH = 256
EMAIL_MAX_LENGTH = 320
# User.subject の列長。大文字小文字の統一（casefold）で文字数が増えるため、統一後の長さも検査する
SUBJECT_MAX_LENGTH = 512


class UserError(ValueError):
    """ユーザー操作の入力エラー（日本語メッセージ）。"""


class DuplicateUserError(UserError):
    """同じ realm に同じユーザーが既にいる。"""

    def __init__(self) -> None:
        super().__init__("同じユーザー名のローカルユーザーが既に存在します。")


class LastAdminError(UserError):
    """最後の有効な admin を降格・無効化・削除しようとした。"""

    def __init__(self) -> None:
        super().__init__("最後の有効な admin は降格・無効化・削除できません。")


# asyncio.Lock は最初に競合したイベントループに束縛されるため、ループごとに用意する
# （本番のループは 1 つだが、テストはテストごとに別のループで動く）。
_admin_change_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def _admin_change_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _admin_change_locks.get(loop)
    if lock is None:
        lock = _admin_change_locks[loop] = asyncio.Lock()
    return lock


@asynccontextmanager
async def admin_change_guard(db: AsyncSession) -> AsyncIterator[None]:
    """有効な admin の人数に影響する変更を直列化する。

    「人数を数えてから変更する」間に別の変更が割り込むと、admin が 0 人になり得る。
    プロセス内は ``asyncio.Lock`` で、PostgreSQL では有効な admin 行を ``FOR UPDATE``
    でロックして他プロセスとも直列化する（SQLite は書き込みが DB 単位で直列）。
    ブロックの最後で commit し、ロックを放す前に変更を確定させる。
    """
    async with _admin_change_lock():
        await db.execute(
            select(User.id)
            .where(User.role == Role.ADMIN.value, User.is_active.is_(True))
            .order_by(User.id)
            .with_for_update()
        )
        yield
        await db.commit()


async def ensure_not_last_admin(db: AsyncSession, user: User) -> None:
    """``admin_change_guard`` の中で呼ぶこと。"""
    if user.role == Role.ADMIN.value and user.is_active and await count_active_admins(db) <= 1:
        raise LastAdminError()


def normalize_username(username: str) -> str:
    """前後の空白を除き NFKC 正規化する。空・制御文字・長すぎる値は拒否。"""
    value = unicodedata.normalize("NFKC", username).strip()
    if not value:
        raise UserError("ユーザー名を入力してください。")
    if len(value) > USERNAME_MAX_LENGTH:
        raise UserError(f"ユーザー名は {USERNAME_MAX_LENGTH} 文字以下にしてください。")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise UserError("ユーザー名に制御文字は使えません。")
    if len(value.casefold()) > SUBJECT_MAX_LENGTH:
        # 例: U+0390 は casefold で 3 文字になる
        raise UserError("ユーザー名が長すぎます。")
    return value


def normalize_optional_text(value: str | None, *, max_length: int, label: str) -> str | None:
    """表示名・メールなど任意項目の正規化。空は ``None``、長すぎる値と制御文字は拒否。

    SQLite は VARCHAR の長さを強制しないため、DB に任せず列長をここで検査する。
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        raise UserError(f"{label}は {max_length} 文字以下にしてください。")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise UserError(f"{label}に制御文字は使えません。")
    return text


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
    display_name = normalize_optional_text(
        display_name, max_length=DISPLAY_NAME_MAX_LENGTH, label="表示名"
    )
    email = normalize_optional_text(email, max_length=EMAIL_MAX_LENGTH, label="メールアドレス")
    validate_password_policy(password, min_length=password_min_length)
    if await get_local_user(db, name) is not None:
        raise DuplicateUserError()
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
    try:
        await db.flush()
    except IntegrityError:
        # 事前確認の後に同名ユーザーが同時に作られた場合。呼び出し側でロールバックすること。
        raise DuplicateUserError() from None
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
    if keep_session_id is not None:
        # 変更操作をしたセッションだけは新しい世代に付け替えて残す
        await db.execute(
            update(AuthSession)
            .where(AuthSession.id == keep_session_id, AuthSession.user_id == user.id)
            .values(credential_marker=credential_marker(user))
        )
    await db.flush()


def unlock_user(user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None
