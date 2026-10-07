"""サーバ側ログインセッションの作成・解決・失効。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.auth.tokens import hash_token, new_session_token
from vcenter_event_assistant.db.models import AuthSession, User

# last_seen_at の更新はこの間隔より古いときだけ行う（毎リクエストの書き込みを避ける）。
# 無操作タイムアウトが短い設定でも、アクセスが続く限り失効しないよう ``touch_interval`` で縮める。
TOUCH_INTERVAL = timedelta(seconds=60)

_CLIENT_IP_MAX = 64
_USER_AGENT_MAX = 256


@dataclass(frozen=True)
class SessionPolicy:
    idle_timeout: timedelta
    absolute_timeout: timedelta

    @property
    def touch_interval(self) -> timedelta:
        """無操作タイムアウトの半分を上限にする（1 分の設定でも 30 秒ごとに延長される）。"""
        return min(TOUCH_INTERVAL, self.idle_timeout / 2)


def credential_marker(user: User) -> str | None:
    """パスワードの世代を表す値。変更されるたびに変わる（ディレクトリユーザーは ``None``）。

    ログイン中にパスワードが変更された場合でも、古いパスワードで認証したセッションは
    この値が一致しなくなるため、どの順序で処理が割り込んでも有効にならない。
    """
    if user.password_changed_at is None:
        return None
    return as_utc(user.password_changed_at).isoformat()


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
            credential_marker=credential_marker(user),
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
        if await _delete_if_still_expired(db, row, policy, now):
            return None
        # 読み込んだ後に別のリクエストが last_seen_at を進めていた。最新の行で判定し直す
        await db.refresh(row)
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active or row.credential_marker != credential_marker(user):
        # 無効化されたユーザーのセッションも消す（再度有効にしたときに復活させないため）
        await db.delete(row)
        await db.flush()
        return None
    if now - as_utc(row.last_seen_at) >= policy.touch_interval:
        await _touch(db, row, now)
    return ResolvedSession(session=row, user=user)


async def _delete_if_still_expired(
    db: AsyncSession, row: AuthSession, policy: SessionPolicy, now: datetime
) -> bool:
    """期限切れの条件を DB 上で再評価して削除する。削除したら ``True``。

    読み込んだ値だけで判断して主キーで消すと、その間に重なったリクエストが確定させた
    更新ごと、使用中のセッションを消してしまうため。
    """
    done = await db.execute(
        delete(AuthSession)
        .where(
            AuthSession.id == row.id,
            or_(
                AuthSession.expires_at <= now,
                AuthSession.last_seen_at <= now - policy.idle_timeout,
            ),
        )
        .execution_options(synchronize_session=False)
    )
    if done.rowcount:
        db.expunge(row)
        return True
    return False


async def _touch(db: AsyncSession, row: AuthSession, now: datetime) -> None:
    """``last_seen_at`` を進める。DB 上の値より新しいときだけ書き込み、巻き戻さない。

    同じトークンのリクエストが重なると、遅れて確定した側が古い時刻で上書きし、
    使用中のセッションが早く無操作タイムアウトになり得るため。
    """
    done = await db.execute(
        update(AuthSession)
        .where(AuthSession.id == row.id, AuthSession.last_seen_at < now)
        .values(last_seen_at=now)
        .execution_options(synchronize_session=False)
    )
    if done.rowcount:
        set_committed_value(row, "last_seen_at", now)


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
