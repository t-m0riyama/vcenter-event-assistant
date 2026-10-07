"""サーバ側ログインセッションの作成・解決・失効。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.auth.tokens import hash_token, new_session_token
from vcenter_event_assistant.db.models import AuthSession, User

# last_seen_at の更新はこの間隔より古いときだけ行う（毎リクエストの書き込みを避ける）。
TOUCH_INTERVAL = timedelta(seconds=60)

_CLIENT_IP_MAX = 64
_USER_AGENT_MAX = 256


@dataclass(frozen=True)
class SessionPolicy:
    idle_timeout: timedelta
    absolute_timeout: timedelta


@dataclass(frozen=True)
class ResolvedSession:
    session: AuthSession
    user: User


async def create_session(
    db: AsyncSession,
    user: User,
    policy: SessionPolicy,
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> str:
    """新しいセッションを作り、Cookie に入れる生トークンを返す（DB にはハッシュのみ）。"""
    now = now or utcnow()
    token = new_session_token()
    db.add(
        AuthSession(
            token_hash=hash_token(token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + policy.absolute_timeout,
            client_ip=(client_ip or None) and client_ip[:_CLIENT_IP_MAX],
            user_agent=(user_agent or None) and user_agent[:_USER_AGENT_MAX],
        )
    )
    await db.flush()
    return token


def _is_expired(row: AuthSession, policy: SessionPolicy, now: datetime) -> bool:
    if as_utc(row.expires_at) <= now:
        return True
    return as_utc(row.last_seen_at) + policy.idle_timeout <= now


async def resolve_session(
    db: AsyncSession,
    token: str | None,
    policy: SessionPolicy,
    *,
    now: datetime | None = None,
) -> ResolvedSession | None:
    """トークンから有効なセッションとユーザーを返す。期限切れ・無効ユーザーは ``None``。"""
    if not token:
        return None
    now = now or utcnow()
    row = await db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if row is None:
        return None
    if _is_expired(row, policy, now):
        await db.delete(row)
        await db.flush()
        return None
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    if now - as_utc(row.last_seen_at) >= TOUCH_INTERVAL:
        row.last_seen_at = now
        await db.flush()
    return ResolvedSession(session=row, user=user)


async def revoke_session(db: AsyncSession, token: str | None) -> None:
    if not token:
        return
    await db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))


async def revoke_all_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    except_session_id: uuid.UUID | None = None,
) -> None:
    """ロール変更・無効化・パスワード変更時に、そのユーザーのセッションを全部失効させる。"""
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if except_session_id is not None:
        stmt = stmt.where(AuthSession.id != except_session_id)
    await db.execute(stmt)


async def purge_expired_sessions(
    db: AsyncSession,
    policy: SessionPolicy,
    *,
    now: datetime | None = None,
) -> int:
    now = now or utcnow()
    result = await db.execute(
        delete(AuthSession).where(
            or_(
                AuthSession.expires_at <= now,
                AuthSession.last_seen_at <= now - policy.idle_timeout,
            )
        )
    )
    return int(result.rowcount or 0)
