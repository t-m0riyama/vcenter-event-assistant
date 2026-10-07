"""認証の土台: ロール、パスワード、セッション、ローカルユーザー操作。"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from vcenter_event_assistant.auth.passwords import (
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
    verify_password,
)
from vcenter_event_assistant.auth.roles import Role, highest_role, role_at_least
from vcenter_event_assistant.auth.sessions import (
    SessionPolicy,
    create_session,
    purge_expired_sessions,
    resolve_session,
    revoke_all_for_user,
    revoke_session,
)
from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.auth.tokens import hash_token
from vcenter_event_assistant.auth.users import _admin_change_lock as admin_change_guard_lock
from vcenter_event_assistant.auth.users import (
    UserError,
    create_local_user,
    get_local_user,
    set_local_password,
)
from vcenter_event_assistant.db.models import AuthSession
from vcenter_event_assistant.db.session import session_scope

POLICY = SessionPolicy(idle_timeout=timedelta(minutes=60), absolute_timeout=timedelta(hours=12))
PASSWORD = "correct horse battery"


def test_role_ordering() -> None:
    assert role_at_least(Role.ADMIN, Role.OPERATOR)
    assert role_at_least("operator", "operator")
    assert not role_at_least(Role.VIEWER, Role.OPERATOR)
    assert highest_role(["viewer", "admin", "operator"]) is Role.ADMIN
    assert highest_role([]) is None


@pytest.mark.parametrize(
    "password",
    ["short", " leading-space-pw", "trailing-space-pw ", "has\ncontrol-char", "x" * 257],
)
def test_password_policy_rejects(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password_policy(password, min_length=12)


async def test_password_hash_roundtrip() -> None:
    hashed = await hash_password(PASSWORD)
    assert hashed.startswith("$argon2id$")
    assert PASSWORD not in hashed
    assert (await verify_password(hashed, PASSWORD)).ok
    assert not (await verify_password(hashed, "wrong password!!")).ok
    assert not (await verify_password(None, PASSWORD)).ok
    assert not (await verify_password("not-a-hash", PASSWORD)).ok


async def test_create_local_user_is_case_insensitive_unique() -> None:
    async with session_scope() as db:
        user = await create_local_user(
            db, username="  Alice ", password=PASSWORD, role="operator", password_min_length=12
        )
        assert user.username == "Alice"
        assert user.subject == "alice"
        assert user.realm_key == "local"
        with pytest.raises(UserError):
            await create_local_user(
                db, username="ALICE", password=PASSWORD, role="viewer", password_min_length=12
            )
    async with session_scope() as db:
        found = await get_local_user(db, "alice")
        assert found is not None and found.role == "operator"


async def test_username_rejected_when_casefold_overflows_subject() -> None:
    """NFKC 後は 256 文字でも、casefold で subject の列長を超える名前は入力エラーにする。"""
    assert len("\u0390".casefold()) == 3
    async with session_scope() as db:
        with pytest.raises(UserError):
            await create_local_user(
                db, username="\u0390" * 256, password=PASSWORD, role="viewer", password_min_length=12
            )
        ok = await create_local_user(
            db, username="a" * 256, password=PASSWORD, role="viewer", password_min_length=12
        )
        assert len(ok.subject) == 256


async def test_session_lifecycle_stores_only_hash() -> None:
    async with session_scope() as db:
        user = await create_local_user(
            db, username="bob", password=PASSWORD, role="viewer", password_min_length=12
        )
        token = await create_session(db, user, POLICY, client_ip="10.0.0.1", user_agent="ua")
    async with session_scope() as db:
        rows = (await db.scalars(select(AuthSession))).all()
        assert [r.token_hash for r in rows] == [hash_token(token)]
        resolved = await resolve_session(db, token, POLICY)
        assert resolved is not None and resolved.user.username == "bob"
        assert await resolve_session(db, "bogus", POLICY) is None
        assert await resolve_session(db, None, POLICY) is None
        await revoke_session(db, token)
    async with session_scope() as db:
        assert await resolve_session(db, token, POLICY) is None


async def test_session_idle_and_absolute_expiry() -> None:
    now = utcnow()
    async with session_scope() as db:
        user = await create_local_user(
            db, username="carol", password=PASSWORD, role="viewer", password_min_length=12
        )
        token = await create_session(db, user, POLICY, now=now)
    async with session_scope() as db:
        # 59 分後はまだ有効で、last_seen_at が更新される
        assert await resolve_session(db, token, POLICY, now=now + timedelta(minutes=59)) is not None
    async with session_scope() as db:
        # 更新された last_seen_at から 59 分後も有効
        assert await resolve_session(db, token, POLICY, now=now + timedelta(minutes=118)) is not None
    async with session_scope() as db:
        # 絶対期限を過ぎると無効
        assert await resolve_session(db, token, POLICY, now=now + timedelta(hours=12)) is None

    async with session_scope() as db:
        user = await get_local_user(db, "carol")
        assert user is not None
        token2 = await create_session(db, user, POLICY, now=now)
    async with session_scope() as db:
        assert await resolve_session(db, token2, POLICY, now=now + timedelta(minutes=61)) is None


async def test_short_idle_timeout_is_extended_by_activity() -> None:
    """無操作タイムアウトの最小値（1 分）でも、アクセスが続く限り失効しない。"""
    policy = SessionPolicy(idle_timeout=timedelta(minutes=1), absolute_timeout=timedelta(hours=12))
    now = utcnow()
    async with session_scope() as db:
        user = await create_local_user(
            db, username="busy", password=PASSWORD, role="viewer", password_min_length=12
        )
        token = await create_session(db, user, policy, now=now)
    for seconds in range(10, 301, 10):
        async with session_scope() as db:
            at = now + timedelta(seconds=seconds)
            assert await resolve_session(db, token, policy, now=at) is not None, seconds
    async with session_scope() as db:
        # アクセスが途絶えれば 1 分で失効する
        assert await resolve_session(db, token, policy, now=now + timedelta(seconds=361)) is None


async def test_session_touch_never_moves_backwards() -> None:
    """遅れて確定したリクエストが、新しい last_seen_at を古い時刻で上書きしない。"""
    t0 = utcnow()
    async with session_scope() as db:
        user = await create_local_user(
            db, username="touchy", password=PASSWORD, role="viewer", password_min_length=12
        )
        token = await create_session(db, user, POLICY, now=t0)
    async with session_scope() as slow:
        # 先に始まった遅いリクエストが、更新前の行を読み込んで保持している
        # （参照を持たないと identity map から外れ、後で最新値を読み直してしまう）
        stale_row = await slow.scalar(select(AuthSession))
        assert stale_row is not None
        async with session_scope() as fast:
            assert await resolve_session(fast, token, POLICY, now=t0 + timedelta(minutes=10)) is not None
        resolved = await resolve_session(slow, token, POLICY, now=t0 + timedelta(minutes=5))
        assert resolved is not None and resolved.session is stale_row
    async with session_scope() as db:
        row = await db.scalar(select(AuthSession))
        assert row is not None
        assert as_utc(row.last_seen_at) == t0 + timedelta(minutes=10)


async def test_expiry_is_rechecked_before_deleting() -> None:
    """古い last_seen_at で期限切れと判断しても、その間に更新されたセッションは消さない。"""
    t0 = utcnow()
    async with session_scope() as db:
        user = await create_local_user(
            db, username="edge", password=PASSWORD, role="viewer", password_min_length=12
        )
        token = await create_session(db, user, POLICY, now=t0)
    async with session_scope() as slow:
        stale_row = await slow.scalar(select(AuthSession))  # 更新前の行を保持している
        assert stale_row is not None
        async with session_scope() as fast:
            # 無操作タイムアウトの直前に、別のリクエストが使用を記録した
            assert await resolve_session(fast, token, POLICY, now=t0 + timedelta(minutes=59)) is not None
        # 古い値（t0）から見ると 61 分経過しているが、実際は 2 分前に使われている
        resolved = await resolve_session(slow, token, POLICY, now=t0 + timedelta(minutes=61))
        assert resolved is not None
    async with session_scope() as db:
        assert len((await db.scalars(select(AuthSession))).all()) == 1


async def test_inactive_user_session_is_rejected() -> None:
    async with session_scope() as db:
        user = await create_local_user(
            db, username="dave", password=PASSWORD, role="admin", password_min_length=12
        )
        token = await create_session(db, user, POLICY)
        user.is_active = False
    async with session_scope() as db:
        assert await resolve_session(db, token, POLICY) is None
    async with session_scope() as db:
        # 再び有効にしても古いセッションが復活しないよう、行は削除されている
        assert (await db.scalars(select(AuthSession))).all() == []


async def test_password_change_revokes_other_sessions() -> None:
    async with session_scope() as db:
        user = await create_local_user(
            db, username="erin", password=PASSWORD, role="viewer", password_min_length=12
        )
        keep = await create_session(db, user, POLICY)
        other = await create_session(db, user, POLICY)
    async with session_scope() as db:
        resolved = await resolve_session(db, keep, POLICY)
        assert resolved is not None
        user = resolved.user
        user.failed_login_count = 3
        await set_local_password(
            db, user, "another long password", password_min_length=12,
            keep_session_id=resolved.session.id,
        )
        assert user.failed_login_count == 0
    async with session_scope() as db:
        assert await resolve_session(db, keep, POLICY) is not None
        assert await resolve_session(db, other, POLICY) is None
        user = await get_local_user(db, "erin")
        assert user is not None
        await revoke_all_for_user(db, user.id)
    async with session_scope() as db:
        assert await resolve_session(db, keep, POLICY) is None


async def test_session_from_stale_credentials_is_rejected() -> None:
    """パスワード検証中に変更が確定しても、古い世代で作ったセッションは使えない。

    ログイン処理がユーザーを読み込んだ後に別トランザクションでパスワードが変更され、
    その全セッション削除の後でセッションが作られる競合を再現する。
    """
    async with session_scope() as db:
        await create_local_user(
            db, username="race", password=PASSWORD, role="admin", password_min_length=12
        )
    async with session_scope() as login_db:
        stale = await get_local_user(login_db, "race")  # ログイン処理が読み込んだ時点の行
        assert stale is not None
        async with session_scope() as change_db:
            fresh = await get_local_user(change_db, "race")
            assert fresh is not None
            await set_local_password(change_db, fresh, "changed long password", password_min_length=12)
        token = await create_session(login_db, stale, POLICY)
    async with session_scope() as db:
        assert await resolve_session(db, token, POLICY) is None
        # 新しいパスワードでのセッションは有効
        user = await get_local_user(db, "race")
        assert user is not None
        token2 = await create_session(db, user, POLICY)
    async with session_scope() as db:
        assert await resolve_session(db, token2, POLICY) is not None


async def test_purge_expired_sessions() -> None:
    now = utcnow()
    async with session_scope() as db:
        user = await create_local_user(
            db, username="frank", password=PASSWORD, role="viewer", password_min_length=12
        )
        await create_session(db, user, POLICY, now=now - timedelta(hours=13))
        await create_session(db, user, POLICY, now=now)
    async with session_scope() as db:
        assert await purge_expired_sessions(db, POLICY, now=now) == 1
        assert len((await db.scalars(select(AuthSession))).all()) == 1


async def test_deleting_user_cascades_sessions() -> None:
    async with session_scope() as db:
        user = await create_local_user(
            db, username="gina", password=PASSWORD, role="viewer", password_min_length=12
        )
        await create_session(db, user, POLICY)
    async with session_scope() as db:
        user = await get_local_user(db, "gina")
        await db.delete(user)
    async with session_scope() as db:
        assert (await db.scalars(select(AuthSession))).all() == []


@pytest.mark.parametrize("round_", [1, 2])
async def test_admin_change_lock_works_in_each_event_loop(round_: int) -> None:
    """ロックが前のテストのイベントループに束縛されて例外にならない（テストごとに別ループ）。"""
    async def hold() -> None:
        async with admin_change_guard_lock():
            await asyncio.sleep(0)

    await asyncio.gather(hold(), hold())
