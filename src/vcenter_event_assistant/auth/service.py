"""ログイン処理の入口。realm ごとの認証バックエンドへ振り分ける。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.auth.audit import audit
from vcenter_event_assistant.auth.passwords import (
    PASSWORD_MAX_LENGTH,
    hash_password,
    verify_password,
)
from vcenter_event_assistant.auth.sessions import SessionPolicy, credential_marker
from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.auth.users import (
    LOCAL_REALM,
    UserError,
    get_local_user,
    normalize_username,
)
from vcenter_event_assistant.db.models import User
from vcenter_event_assistant.settings import Settings

# 失敗理由（ユーザー不在・パスワード誤り・ロック中・無効化）を画面に出し分けない。
GENERIC_LOGIN_ERROR = "ユーザー名またはパスワードが正しくありません。"


@dataclass(frozen=True)
class Realm:
    id: str
    name: str
    kind: str


@dataclass(frozen=True)
class LoginOutcome:
    user: User | None
    reason: str

    @property
    def ok(self) -> bool:
        return self.user is not None


def session_policy(settings: Settings) -> SessionPolicy:
    return SessionPolicy(
        idle_timeout=timedelta(minutes=settings.session_idle_timeout_minutes),
        absolute_timeout=timedelta(hours=settings.session_absolute_timeout_hours),
    )


async def list_realms(db: AsyncSession, settings: Settings) -> list[Realm]:
    """ログイン画面に出す認証先。"""
    _ = db
    realms: list[Realm] = []
    if settings.local_login_enabled:
        realms.append(Realm(id=LOCAL_REALM, name="ローカル", kind="local"))
    return realms


async def _authenticate_local(
    db: AsyncSession, settings: Settings, username: str, password: str
) -> LoginOutcome:
    try:
        name = normalize_username(username)
    except UserError:
        await verify_password(None, password)
        return LoginOutcome(None, "invalid_username")
    user = await get_local_user(db, name)
    if user is None:
        await verify_password(None, password)
        return LoginOutcome(None, "unknown_user")

    now = utcnow()
    if user.locked_until is not None and as_utc(user.locked_until) > now:
        await verify_password(None, password)
        return LoginOutcome(None, "locked")

    generation = credential_marker(user)
    result = await verify_password(user.password_hash, password)
    if not result.ok:
        if await _record_failure(db, settings, user.id, now):
            audit("login_lockout", level=logging.WARNING, realm=LOCAL_REALM, username=user.username)
        return LoginOutcome(None, "bad_password")

    if not user.is_active:
        return LoginOutcome(None, "inactive")

    await db.refresh(user)
    if credential_marker(user) != generation or not user.is_active:
        # 検証している間にパスワード変更・無効化が確定した。これより後の変更は
        # セッションの世代照合（sessions.credential_marker）で無効になる。
        return LoginOutcome(None, "credential_changed")
    if not await _record_success(db, user.id, now):
        # 検証している間に、並行した失敗でロックされた
        return LoginOutcome(None, "locked")
    if result.needs_rehash:
        user.password_hash = await hash_password(password)
        await db.flush()
    return LoginOutcome(user, "ok")


# 失敗回数は読み込み済みの値から加算せず、DB 上で原子的に更新する。
# 並行した失敗が互いの加算を上書きすると、複数 IP からの試行でロックアウトを回避できるため。
_NO_SYNC = {"synchronize_session": False}


async def _record_failure(
    db: AsyncSession, settings: Settings, user_id: uuid.UUID, now: datetime
) -> bool:
    """失敗回数を 1 増やし、閾値に達したらロックする。ロックしたら ``True``。"""
    count = await db.scalar(
        update(User)
        .where(User.id == user_id)
        .values(failed_login_count=User.failed_login_count + 1)
        .returning(User.failed_login_count)
        .execution_options(**_NO_SYNC)
    )
    if count is None or count < settings.login_max_failed_attempts:
        return False
    locked = await db.execute(
        update(User)
        .where(User.id == user_id, User.failed_login_count >= settings.login_max_failed_attempts)
        .values(
            locked_until=now + timedelta(minutes=settings.login_lockout_minutes),
            failed_login_count=0,
        )
        .execution_options(**_NO_SYNC)
    )
    return bool(locked.rowcount)


async def _record_success(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> bool:
    """ロックされていなければ失敗回数を戻して ``True``。ロック中なら ``False``。"""
    done = await db.execute(
        update(User)
        .where(
            User.id == user_id,
            or_(User.locked_until.is_(None), User.locked_until <= now),
        )
        .values(failed_login_count=0, locked_until=None, last_login_at=now)
        .execution_options(**_NO_SYNC)
    )
    return bool(done.rowcount)


async def authenticate(
    db: AsyncSession,
    settings: Settings,
    *,
    realm: str,
    username: str,
    password: str,
    client_ip: str | None,
) -> LoginOutcome:
    """認証して ``LoginOutcome`` を返す。成否はすべて監査ログに残す。"""
    if not password or len(password) > PASSWORD_MAX_LENGTH * 4:
        # 空パスワードは LDAP の unauthenticated bind で成功扱いになり得るため常に拒否する
        outcome = LoginOutcome(None, "empty_password" if not password else "too_long")
    elif realm == LOCAL_REALM and settings.local_login_enabled:
        outcome = await _authenticate_local(db, settings, username, password)
    else:
        await verify_password(None, password)
        outcome = LoginOutcome(None, "unknown_realm")

    if outcome.ok:
        assert outcome.user is not None
        audit("login_success", realm=realm, username=outcome.user.username, role=outcome.user.role, ip=client_ip)
    else:
        audit(
            "login_failure",
            level=logging.WARNING,
            realm=realm,
            username=username[:256],
            reason=outcome.reason,
            ip=client_ip,
        )
    return outcome
