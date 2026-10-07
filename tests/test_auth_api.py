"""ログイン API、セッション Cookie、CSRF、ロックアウト、認証無効時の挙動。"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from vcenter_event_assistant.auth.service import GENERIC_LOGIN_ERROR
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.auth.users import create_local_user, get_local_user, set_local_password
from vcenter_event_assistant.db.session import session_scope
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
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test", **kwargs)


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
        assert "httponly" in lowered and "samesite=strict" in lowered and "path=/" in lowered

        me = await ac.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json() == {
            "auth_enabled": True,
            "username": "alice",
            "display_name": None,
            "role": "operator",
            "realm": "local",
            "can_change_password": True,
        }
        assert (await ac.get("/api/config")).status_code == 200

        assert (await ac.post("/api/auth/logout", headers=XHR)).status_code == 204
        assert (await ac.get("/api/auth/me")).status_code == 401


@pytest.mark.parametrize(
    ("username", "password"),
    [("alice", "wrong password!!"), ("nobody", PASSWORD), ("alice", "")],
)
async def test_login_failures_share_generic_message(username: str, password: str, caplog) -> None:
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
            json={"current_password": "wrong password!!", "new_password": "brand new password"},
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
    async def test_mutation_without_header_is_rejected(self, client: AsyncClient) -> None:
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
    async def test_same_host_and_trusted_origin_pass(self, client: AsyncClient, origin: str) -> None:
        resp = await client.patch("/api/events/999999", json={}, headers={"Origin": origin})
        assert resp.status_code != 403

    async def test_safe_methods_are_not_checked(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/config", headers={"X-Requested-With": "", "Origin": "https://evil.example"}
        )
        assert resp.status_code == 200


async def test_production_cookie_is_host_prefixed_and_secure(monkeypatch: pytest.MonkeyPatch) -> None:
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


async def test_auth_disabled_keeps_legacy_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert (await ac.get("/api/auth/realms")).json() == {"auth_enabled": False, "realms": []}


async def test_login_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VEA_PYTEST")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_MINUTE", "2")
    get_settings.cache_clear()
    _rate_limiter._hits.clear()
    try:
        async with _raw_client() as ac:
            codes = [(await _login(ac, password="wrong password!!")).status_code for _ in range(3)]
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
                await set_local_password(db, user, "changed long password", password_min_length=12)

        self._pause_verification(monkeypatch, change_password)
        async with _raw_client() as ac:
            resp = await _login(ac)
            assert resp.status_code == 401
            assert (await ac.get("/api/auth/me")).status_code == 401

    async def test_concurrent_failures_reach_lockout(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
