"""ログイン API、セッション Cookie、CSRF、ロックアウト、認証無効時の挙動。"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from vcenter_event_assistant.auth.passwords import verify_password
from vcenter_event_assistant.auth.service import GENERIC_LOGIN_ERROR, session_policy
from vcenter_event_assistant.auth.sessions import create_session
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.auth.users import (
    create_local_user,
    get_local_user,
    set_local_password,
)
from vcenter_event_assistant.db.models import AuthSession
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.jobs.scheduler import purge_retention
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.rate_limit import _rate_limiter
from vcenter_event_assistant.settings import get_settings

PASSWORD = "correct horse battery"
XHR = {"X-Requested-With": "XMLHttpRequest"}


async def _make_user(username: str = "alice", role: str = "operator") -> None:
    async with session_scope() as db:
        await create_local_user(
            db, username=username, password=PASSWORD, role=role, password_min_length=12
        )


def _raw_client(**kwargs) -> AsyncClient:
    """ヘッダも Cookie も持たない素のクライアント。"""
    return AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test", **kwargs
    )


async def _login(ac: AsyncClient, username: str = "alice", password: str = PASSWORD):
    return await ac.post(
        "/api/auth/login",
        json={"username": username, "password": password, "realm": "local"},
        headers=XHR,
    )


async def test_login_sets_hardened_cookie_and_me_works() -> None:
    await _make_user()
    async with _raw_client() as ac:
        resp = await _login(ac, username="ALICE")
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "operator"
        cookie = resp.headers["set-cookie"]
        assert cookie.startswith("vea_session=")
        lowered = cookie.lower()
        assert (
            "httponly" in lowered
            and "samesite=strict" in lowered
            and "path=/" in lowered
        )

        me = await ac.get("/api/auth/me")
        assert me.status_code == 200
        body = me.json()
        principal_id = body.pop("principal_id")
        assert principal_id and me.headers["x-vea-principal"] == principal_id
        assert body == {
            "auth_enabled": True,
            "username": "alice",
            "display_name": None,
            "role": "operator",
            "realm": "local",
            "can_change_password": True,
            # 既定の無操作 60 分では、サーバは 60 秒ごとに最終利用時刻を更新する
            "session_activity_interval_seconds": 60,
        }
        assert (await ac.get("/api/config")).status_code == 200

        assert (await ac.post("/api/auth/logout", headers=XHR)).status_code == 204
        assert (await ac.get("/api/auth/me")).status_code == 401


@pytest.mark.parametrize(
    ("username", "password"),
    [("alice", "wrong password!!"), ("nobody", PASSWORD), ("alice", "")],
)
async def test_login_failures_share_generic_message(
    username: str, password: str, caplog
) -> None:
    await _make_user()
    async with _raw_client() as ac:
        # create_app が logging を再設定して root の caplog ハンドラを外すため、監査 logger に直接付ける
        audit_logger = logging.getLogger("vcenter_event_assistant.audit")
        audit_logger.addHandler(caplog.handler)
        try:
            resp = await _login(ac, username=username, password=password)
        finally:
            audit_logger.removeHandler(caplog.handler)
    assert resp.status_code == 401
    assert resp.json() == {"detail": GENERIC_LOGIN_ERROR}
    assert "set-cookie" not in resp.headers
    assert "event=login_failure" in caplog.text
    assert PASSWORD not in caplog.text


async def test_unknown_realm_is_rejected() -> None:
    await _make_user()
    async with _raw_client() as ac:
        resp = await ac.post(
            "/api/auth/login",
            json={"username": "alice", "password": PASSWORD, "realm": "dir:nope"},
            headers=XHR,
        )
    assert resp.status_code == 401


async def test_lockout_after_repeated_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEA_LOGIN_MAX_FAILED_ATTEMPTS", "3")
    get_settings.cache_clear()
    await _make_user()
    async with _raw_client() as ac:
        for _ in range(3):
            assert (await _login(ac, password="wrong password!!")).status_code == 401
        # ロック中は正しいパスワードでも同じ文言で拒否する
        locked = await _login(ac)
        assert locked.status_code == 401
        assert locked.json() == {"detail": GENERIC_LOGIN_ERROR}
    async with session_scope() as db:
        user = await get_local_user(db, "alice")
        assert user is not None and user.locked_until is not None
        user.locked_until = None
    async with _raw_client() as ac:
        assert (await _login(ac)).status_code == 200


async def test_inactive_user_cannot_login() -> None:
    await _make_user()
    async with session_scope() as db:
        user = await get_local_user(db, "alice")
        assert user is not None
        user.is_active = False
    async with _raw_client() as ac:
        assert (await _login(ac)).status_code == 401


async def test_login_rotates_existing_session() -> None:
    await _make_user()
    async with _raw_client() as ac:
        await _login(ac)
        old = ac.cookies.get("vea_session")
        await _login(ac)
        new = ac.cookies.get("vea_session")
        assert old and new and old != new
    async with _raw_client(cookies={"vea_session": old}) as stale:
        assert (await stale.get("/api/auth/me")).status_code == 401


async def test_change_own_password() -> None:
    await _make_user()
    async with _raw_client() as ac, _raw_client() as other:
        await _login(ac)
        await _login(other)
        bad = await ac.post(
            "/api/auth/me/password",
            json={
                "current_password": "wrong password!!",
                "new_password": "brand new password",
            },
            headers=XHR,
        )
        assert bad.status_code == 400
        weak = await ac.post(
            "/api/auth/me/password",
            json={"current_password": PASSWORD, "new_password": "short"},
            headers=XHR,
        )
        assert weak.status_code == 400
        ok = await ac.post(
            "/api/auth/me/password",
            json={"current_password": PASSWORD, "new_password": "brand new password"},
            headers=XHR,
        )
        assert ok.status_code == 204
        # 変更したセッションは残り、他のセッションは失効する
        assert (await ac.get("/api/auth/me")).status_code == 200
        assert (await other.get("/api/auth/me")).status_code == 401
    async with _raw_client() as ac:
        assert (await _login(ac, password="brand new password")).status_code == 200


async def test_realms_lists_local() -> None:
    async with _raw_client() as ac:
        resp = await ac.get("/api/auth/realms")
    assert resp.json() == {
        "auth_enabled": True,
        "realms": [{"id": "local", "name": "ローカル", "kind": "local"}],
    }


async def test_local_login_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEA_LOCAL_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    await _make_user()
    async with _raw_client() as ac:
        assert (await ac.get("/api/auth/realms")).json()["realms"] == []
        assert (await _login(ac)).status_code == 401


class TestCsrf:
    async def test_mutation_without_header_is_rejected(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post("/api/ingest/run", headers={"X-Requested-With": ""})
        assert resp.status_code == 403
        assert resp.json()["code"] == "csrf_missing_header"

    async def test_login_without_header_is_rejected(self) -> None:
        await _make_user()
        async with _raw_client() as ac:
            resp = await ac.post(
                "/api/auth/login", json={"username": "alice", "password": PASSWORD}
            )
        assert resp.status_code == 403

    async def test_foreign_origin_is_rejected(self, client: AsyncClient) -> None:
        resp = await client.patch(
            "/api/events/1", json={}, headers={"Origin": "https://evil.example"}
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "csrf_origin_mismatch"

    @pytest.mark.parametrize("origin", ["http://test", "http://localhost:5173"])
    async def test_same_host_and_trusted_origin_pass(
        self, client: AsyncClient, origin: str
    ) -> None:
        resp = await client.patch(
            "/api/events/999999", json={}, headers={"Origin": origin}
        )
        assert resp.status_code != 403

    async def test_safe_methods_are_not_checked(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/config",
            headers={"X-Requested-With": "", "Origin": "https://evil.example"},
        )
        assert resp.status_code == 200


async def test_production_cookie_is_host_prefixed_and_secure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("VEA_SECRET_KEY", "prod-secret-key")
    monkeypatch.setenv("VCENTER_ALLOWED_HOST_SUFFIXES", "example.com")
    monkeypatch.setenv("VEA_ALLOW_PLAINTEXT_PASSWORDS", "0")
    get_settings.cache_clear()
    await _make_user()
    async with _raw_client() as ac:
        resp = await _login(ac)
    assert resp.status_code == 200
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith("__Host-vea_session=")
    assert "secure" in cookie.lower()


async def test_auth_disabled_keeps_legacy_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VEA_AUTH_ENABLED", "false")
    get_settings.cache_clear()
    async with _raw_client() as ac:
        assert (await ac.get("/api/config")).status_code == 200
        me = await ac.get("/api/auth/me")
        assert me.json()["auth_enabled"] is False
        assert me.json()["role"] == "admin"
        # CSRF ミドルウェアも入らない（従来どおり）
        assert (await ac.patch("/api/events/999999", json={})).status_code != 403
        assert (await _login(ac)).status_code == 404
        assert (await ac.get("/api/auth/realms")).json() == {
            "auth_enabled": False,
            "realms": [],
        }


async def test_login_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VEA_PYTEST")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_MINUTE", "2")
    get_settings.cache_clear()
    _rate_limiter._hits.clear()
    try:
        async with _raw_client() as ac:
            codes = [
                (await _login(ac, password="wrong password!!")).status_code
                for _ in range(3)
            ]
    finally:
        _rate_limiter._hits.clear()
    assert codes == [401, 401, 429]


class TestLoginRaces:
    """パスワード検証（スレッドで実行される待ち時間）に他の処理が割り込む競合。"""

    @staticmethod
    def _pause_verification(monkeypatch: pytest.MonkeyPatch, during) -> None:
        """実ハッシュの検証が終わった直後に ``during()`` を割り込ませる。"""
        from vcenter_event_assistant.auth import service

        original = service.verify_password

        async def paused(password_hash, password):
            result = await original(password_hash, password)
            if password_hash is not None:
                await during()
            return result

        monkeypatch.setattr(service, "verify_password", paused)

    async def test_password_change_during_login_invalidates_new_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _make_user()

        async def change_password() -> None:
            async with session_scope() as db:
                user = await get_local_user(db, "alice")
                assert user is not None
                await set_local_password(
                    db, user, "changed long password", password_min_length=12
                )

        self._pause_verification(monkeypatch, change_password)
        async with _raw_client() as ac:
            resp = await _login(ac)
            assert resp.status_code == 401
            assert (await ac.get("/api/auth/me")).status_code == 401

    async def test_user_deleted_during_login_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _make_user()

        async def delete_user() -> None:
            async with session_scope() as db:
                user = await get_local_user(db, "alice")
                assert user is not None
                await db.delete(user)

        self._pause_verification(monkeypatch, delete_user)
        async with _raw_client() as ac:
            assert (await _login(ac)).status_code == 401

    async def test_concurrent_failures_reach_lockout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VEA_LOGIN_MAX_FAILED_ATTEMPTS", "2")
        get_settings.cache_clear()
        await _make_user()

        both_verified = asyncio.Barrier(2)
        first_finished = asyncio.Event()
        arrival = iter(range(2))

        async def wait_for_other() -> None:
            # 2 件とも失敗回数を読み込み・検証し終えた状態にする（競合の本質）
            await both_verified.wait()
            # 書き込みは 1 件ずつ確定させる。テストの DB は 1 本の接続を共有しており、
            # 先に終わったリクエストの後始末（ROLLBACK）が他方の未確定の書き込みを消すため。
            if next(arrival) == 1:
                await first_finished.wait()

        async def attempt(ac: AsyncClient):
            resp = await _login(ac, password="wrong password!!")
            first_finished.set()
            return resp

        self._pause_verification(monkeypatch, wait_for_other)
        async with _raw_client() as a, _raw_client() as b:
            results = await asyncio.gather(attempt(a), attempt(b))
        assert [r.status_code for r in results] == [401, 401]
        async with session_scope() as db:
            user = await get_local_user(db, "alice")
            assert user is not None and user.locked_until is not None

    async def test_lock_set_during_verification_rejects_login(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _make_user()

        async def lock_account() -> None:
            async with session_scope() as db:
                user = await get_local_user(db, "alice")
                assert user is not None
                user.locked_until = utcnow() + timedelta(minutes=15)

        self._pause_verification(monkeypatch, lock_account)
        async with _raw_client() as ac:
            assert (await _login(ac)).status_code == 401


class TestCredentialOverwriteRaces:
    """検証済みの古いパスワードで、後から確定した新しいパスワードを上書きしない。"""

    async def test_concurrent_own_password_change_does_not_overwrite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _make_user()
        from vcenter_event_assistant.api.routes import auth as auth_routes

        original = auth_routes.verify_password

        async def paused(password_hash, password):
            result = await original(password_hash, password)
            # 現在のパスワードの検証中に、正規の利用者が別途パスワードを変更した
            async with session_scope() as db:
                user = await get_local_user(db, "alice")
                assert user is not None
                await set_local_password(
                    db, user, "owner chosen password", password_min_length=12
                )
            return result

        async with _raw_client() as ac:
            assert (await _login(ac)).status_code == 200
            monkeypatch.setattr(auth_routes, "verify_password", paused)
            resp = await ac.post(
                "/api/auth/me/password",
                json={
                    "current_password": PASSWORD,
                    "new_password": "attacker chosen password",
                },
                headers=XHR,
            )
        assert resp.status_code == 409
        async with session_scope() as db:
            user = await get_local_user(db, "alice")
            assert user is not None
            assert (
                await verify_password(user.password_hash, "owner chosen password")
            ).ok
            assert not (
                await verify_password(user.password_hash, "attacker chosen password")
            ).ok

    async def test_login_rehash_does_not_restore_old_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # パラメータが古いハッシュで作り、ログイン時の再ハッシュを発生させる
        weak_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(
            PASSWORD
        )
        await _make_user()
        async with session_scope() as db:
            user = await get_local_user(db, "alice")
            assert user is not None
            user.password_hash = weak_hash

        from vcenter_event_assistant.auth import service

        original = service.hash_password

        async def paused(password: str) -> str:
            new_hash = await original(password)
            # 再ハッシュの計算中にパスワード変更が確定した
            async with session_scope() as db:
                user = await get_local_user(db, "alice")
                assert user is not None
                await set_local_password(
                    db, user, "changed long password", password_min_length=12
                )
            return new_hash

        monkeypatch.setattr(service, "hash_password", paused)
        async with _raw_client() as ac:
            await _login(ac)
            # 古い世代で作られたセッションは使えない
            assert (await ac.get("/api/auth/me")).status_code == 401
        async with session_scope() as db:
            user = await get_local_user(db, "alice")
            assert user is not None
            assert (
                await verify_password(user.password_hash, "changed long password")
            ).ok
            assert not (await verify_password(user.password_hash, PASSWORD)).ok


async def test_login_rehashes_outdated_hash() -> None:
    weak_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    await _make_user()
    async with session_scope() as db:
        user = await get_local_user(db, "alice")
        assert user is not None
        user.password_hash = weak_hash
    async with _raw_client() as ac:
        assert (await _login(ac)).status_code == 200
        assert (await ac.get("/api/auth/me")).status_code == 200
    async with session_scope() as db:
        user = await get_local_user(db, "alice")
        assert user is not None and user.password_hash != weak_hash
        assert (await verify_password(user.password_hash, PASSWORD)).ok


async def test_expired_session_row_is_deleted_on_401() -> None:
    await _make_user()
    async with _raw_client() as ac:
        await _login(ac)
        async with session_scope() as db:
            await db.execute(
                update(AuthSession).values(expires_at=utcnow() - timedelta(seconds=1))
            )
        assert (await ac.get("/api/auth/me")).status_code == 401
    async with session_scope() as db:
        assert (await db.scalars(select(AuthSession))).all() == []


async def test_purge_retention_removes_expired_sessions() -> None:
    settings = get_settings()
    now = utcnow()
    async with session_scope() as db:
        user = await create_local_user(
            db,
            username="sess",
            password="session long pw",
            role="viewer",
            password_min_length=12,
        )
        await create_session(
            db, user, session_policy(settings), now=now - timedelta(days=2)
        )
        await create_session(db, user, session_policy(settings), now=now)
    await purge_retention(settings)
    async with session_scope() as db:
        assert len((await db.scalars(select(AuthSession))).all()) == 1


async def test_audit_log_escapes_control_characters(caplog) -> None:
    async with _raw_client() as ac:
        audit_logger = logging.getLogger("vcenter_event_assistant.audit")
        audit_logger.addHandler(caplog.handler)
        try:
            await ac.post(
                "/api/auth/login",
                json={
                    "username": "evil\x1b[31m\x00name",
                    "password": "x",
                    "realm": "loc\x07al",
                },
                headers=XHR,
            )
        finally:
            audit_logger.removeHandler(caplog.handler)
    line = next(
        r.getMessage() for r in caplog.records if "login_failure" in r.getMessage()
    )
    assert not any(ch in line for ch in ("\x1b", "\x00", "\x07"))
    assert "\\x1b" in line and "\\x00" in line and "\\x07" in line


async def test_background_requests_do_not_extend_idle_timeout() -> None:
    """画面の定期更新（X-VEA-Background: 1）では無操作期限を延ばさない。利用者の操作では延ばす。"""
    await _make_user()
    async with _raw_client() as ac:
        assert (await _login(ac)).status_code == 200
        old = utcnow() - timedelta(minutes=30)
        async with session_scope() as db:
            await db.execute(update(AuthSession).values(last_seen_at=old))

        resp = await ac.get("/api/config", headers={"X-VEA-Background": "1"})
        assert resp.status_code == 200
        async with session_scope() as db:
            row = await db.scalar(select(AuthSession))
            assert row is not None
            assert (
                abs(
                    (
                        row.last_seen_at.replace(tzinfo=None) - old.replace(tzinfo=None)
                    ).total_seconds()
                )
                < 1
            )

        assert (await ac.get("/api/config")).status_code == 200
        async with session_scope() as db:
            row = await db.scalar(select(AuthSession))
            assert row is not None
            assert row.last_seen_at.replace(tzinfo=None) > old.replace(
                tzinfo=None
            ) + timedelta(minutes=29)


async def test_background_requests_expire_after_idle_timeout() -> None:
    """定期更新だけが続いても、無操作期限を過ぎればセッションは切れる。"""
    await _make_user()
    async with _raw_client() as ac:
        assert (await _login(ac)).status_code == 200
        idle = session_policy(get_settings()).idle_timeout
        async with session_scope() as db:
            await db.execute(
                update(AuthSession).values(
                    last_seen_at=utcnow() - idle - timedelta(seconds=1)
                )
            )
        resp = await ac.get("/api/config", headers={"X-VEA-Background": "1"})
        assert resp.status_code == 401


async def test_activity_interval_follows_short_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """無操作タイムアウトが短い設定では、報告間隔も短くなる（クライアントが期限前に操作を伝えるため）。"""
    monkeypatch.setenv("VEA_SESSION_IDLE_TIMEOUT_MINUTES", "1")
    get_settings.cache_clear()
    await _make_user()
    async with _raw_client() as ac:
        resp = await _login(ac)
        assert resp.json()["session_activity_interval_seconds"] == 30
        assert (await ac.get("/api/auth/me")).json()[
            "session_activity_interval_seconds"
        ] == 30


async def test_touch_is_kept_when_the_route_fails() -> None:
    """ルートがエラーで終わっても（ロールバックされても）、操作による最終利用時刻の更新は残る。"""
    await _make_user()
    async with _raw_client() as ac:
        assert (await _login(ac)).status_code == 200
        old = utcnow() - timedelta(minutes=30)
        async with session_scope() as db:
            await db.execute(update(AuthSession).values(last_seen_at=old))

        # 存在しないイベントの更新 → 404（HTTPException で get_session はロールバックする）
        resp = await ac.patch(
            "/api/events/999999", json={"user_comment": "x"}, headers=XHR
        )
        assert resp.status_code == 404
        async with session_scope() as db:
            row = await db.scalar(select(AuthSession))
            assert row is not None
            assert row.last_seen_at.replace(tzinfo=None) > old.replace(
                tzinfo=None
            ) + timedelta(minutes=29)


async def test_responses_carry_the_principal_id() -> None:
    """認証済みの API 応答には利用者の ID が付き、別アカウントへの切り替わりをクライアントが検知できる。"""
    await _make_user("alice")
    await _make_user("bob")
    async with _raw_client() as ac:
        alice_id = (await _login(ac, "alice")).json()["principal_id"]
        assert (await ac.get("/api/config")).headers["x-vea-principal"] == alice_id
        # 同じブラウザ（Cookie）で別のアカウントにログインし直すと、以後の応答は bob の ID になる
        bob_id = (await _login(ac, "bob")).json()["principal_id"]
        assert bob_id != alice_id
        assert (await ac.get("/api/config")).headers["x-vea-principal"] == bob_id
        # 同じアカウントでログインし直しても（ロール変更でセッションが失効した後など）値は変わる
        bob_again = (await _login(ac, "bob")).json()["principal_id"]
        assert bob_again != bob_id
        assert (await ac.get("/api/config")).headers["x-vea-principal"] == bob_again
        assert (await ac.get("/api/auth/me")).json()["principal_id"] == bob_again
        # 未ログインの応答には付かない
        await ac.post("/api/auth/logout", headers=XHR)
        resp = await ac.get("/api/config")
        assert resp.status_code == 401 and "x-vea-principal" not in resp.headers


async def test_cors_preflight_allows_the_background_marker(client: AsyncClient) -> None:
    """別オリジンの UI（認証無効の開発構成）でも、定期更新の要求に付く X-VEA-Background が CORS で拒否されない。"""
    resp = await client.options(
        "/api/config",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-vea-background",
        },
    )
    assert resp.status_code == 200
    assert "x-vea-background" in resp.headers["access-control-allow-headers"].lower()


async def test_requests_bound_to_another_principal_are_refused() -> None:
    """別のタブで別の利用者にログインし直された後、前の利用者の画面からの要求は実行しない。"""
    await _make_user("alice")
    await _make_user("bob")
    async with _raw_client() as ac:
        alice_id = (await _login(ac, "alice")).json()["principal_id"]
        bob_id = (await _login(ac, "bob")).json()[
            "principal_id"
        ]  # 別のタブで bob に切り替わった
        # alice の画面からの bob のパスワード変更（現在のパスワードが同じでも）は断る
        resp = await ac.post(
            "/api/auth/me/password",
            json={
                "current_password": PASSWORD,
                "new_password": "another-long-password",
            },
            headers={**XHR, "X-VEA-Expected-Principal": alice_id},
        )
        assert resp.status_code == 409
        assert resp.headers["x-vea-principal"] == bob_id
        # bob のパスワードは変わっていない
        async with _raw_client() as other:
            assert (await _login(other, "bob")).status_code == 200
        # 表示中の利用者と一致していれば通る
        resp = await ac.get("/api/config", headers={"X-VEA-Expected-Principal": bob_id})
        assert resp.status_code == 200


async def test_logout_from_a_stale_tab_keeps_the_new_session() -> None:
    """前の利用者の画面からのログアウトでは、別のタブでログインし直した利用者のセッションを消さない。"""
    await _make_user("alice")
    await _make_user("bob")
    async with _raw_client() as ac:
        alice_id = (await _login(ac, "alice")).json()["principal_id"]
        bob_id = (await _login(ac, "bob")).json()["principal_id"]
        resp = await ac.post(
            "/api/auth/logout", headers={**XHR, "X-VEA-Expected-Principal": alice_id}
        )
        assert resp.status_code == 409
        assert resp.headers["x-vea-principal"] == bob_id
        assert (await ac.get("/api/auth/me")).json()["username"] == "bob"
        # 表示中の利用者と一致していればログアウトする
        resp = await ac.post(
            "/api/auth/logout", headers={**XHR, "X-VEA-Expected-Principal": bob_id}
        )
        assert resp.status_code == 204
        assert (await ac.get("/api/auth/me")).status_code == 401


async def test_browser_downloads_are_bound_by_query() -> None:
    """ヘッダを付けられない CSV のダウンロードも、クエリで渡した表示中の利用者と照合する。"""
    await _make_user("alice")
    await _make_user("bob")
    async with _raw_client() as ac:
        alice_id = (await _login(ac, "alice")).json()["principal_id"]
        bob_id = (await _login(ac, "bob")).json()["principal_id"]
        url = "/api/logs/export.csv"
        resp = await ac.get(
            url, params={"time_zone": "UTC", "vea_expected_principal": alice_id}
        )
        assert resp.status_code == 409
        resp = await ac.get(
            url, params={"time_zone": "UTC", "vea_expected_principal": bob_id}
        )
        assert resp.status_code == 200


async def test_responses_mark_when_the_session_was_touched() -> None:
    """最終利用時刻を更新した応答にだけ印を付ける（クライアントは印で操作が伝わったかを判断する）。"""
    await _make_user("alice")
    async with _raw_client() as ac:
        await _login(ac, "alice")
        async with session_scope() as db:
            row = await db.scalar(select(AuthSession))
            assert row is not None
            row.last_seen_at = row.last_seen_at - timedelta(minutes=5)
            await db.commit()
        first = await ac.get("/api/config")
        assert first.headers.get("x-vea-session-touched") == "1"
        # 更新間隔内の要求は認証を通っても更新しないので、印を付けない
        second = await ac.get("/api/config")
        assert (
            second.status_code == 200 and "x-vea-session-touched" not in second.headers
        )
