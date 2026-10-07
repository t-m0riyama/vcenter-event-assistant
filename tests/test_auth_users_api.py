"""ユーザー管理 API（admin のみ）。"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.auth.users import get_local_user
from vcenter_event_assistant.db.models import AuthSession, User
from vcenter_event_assistant.db.session import session_scope

PASSWORD = "correct horse battery"


async def _create(client: AsyncClient, username: str, role: str = "viewer") -> dict:
    resp = await client.post(
        "/api/auth/users", json={"username": username, "password": PASSWORD, "role": role}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _session_count(username: str) -> int:
    async with session_scope() as db:
        user = await get_local_user(db, username)
        assert user is not None
        rows = await db.scalars(select(AuthSession).where(AuthSession.user_id == user.id))
        return len(rows.all())


async def _login(client: AsyncClient, username: str) -> None:
    """パスワードでログインする（セッションが DB に残る）。"""
    resp = await client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


async def test_create_and_list(client: AsyncClient) -> None:
    created = await _create(client, "Bob", "operator")
    assert created["username"] == "Bob"
    assert created["role"] == "operator"
    assert created["is_local"] is True and created["locked"] is False
    assert "password" not in created and "password_hash" not in created

    names = [u["username"] for u in (await client.get("/api/auth/users")).json()]
    assert "Bob" in names and "test-admin" in names

    dup = await client.post(
        "/api/auth/users", json={"username": "bob", "password": PASSWORD, "role": "viewer"}
    )
    assert dup.status_code == 400
    weak = await client.post(
        "/api/auth/users", json={"username": "weak", "password": "short", "role": "viewer"}
    )
    assert weak.status_code == 400


async def test_role_change_and_deactivation_revoke_sessions(client: AsyncClient, open_client) -> None:
    user = await _create(client, "carol", "operator")
    async with open_client(None) as carol:
        await _login(carol, "carol")
        assert (await carol.get("/api/auth/me")).json()["role"] == "operator"

        resp = await client.patch(f"/api/auth/users/{user['id']}", json={"role": "viewer"})
        assert resp.status_code == 200 and resp.json()["role"] == "viewer"
        assert (await carol.get("/api/auth/me")).status_code == 401

    async with open_client(None) as carol:
        await _login(carol, "carol")
        resp = await client.patch(f"/api/auth/users/{user['id']}", json={"is_active": False})
        assert resp.status_code == 200 and resp.json()["is_active"] is False
        assert (await carol.get("/api/auth/me")).status_code == 401
        relogin = await carol.post("/api/auth/login", json={"username": "carol", "password": PASSWORD})
        assert relogin.status_code == 401


async def test_display_name_change_keeps_sessions(client: AsyncClient, open_client) -> None:
    user = await _create(client, "dave")
    async with open_client(None) as _dave:
        await _login(_dave, "dave")
        resp = await client.patch(
            f"/api/auth/users/{user['id']}", json={"display_name": "Dave D", "email": "d@example.com"}
        )
        assert resp.json()["display_name"] == "Dave D"
        assert await _session_count("dave") == 1


async def test_last_admin_is_protected(open_client) -> None:
    async with open_client("admin", username="only-admin") as admin:
        me = next(u for u in (await admin.get("/api/auth/users")).json() if u["username"] == "only-admin")
        for body in ({"role": "viewer"}, {"is_active": False}):
            resp = await admin.patch(f"/api/auth/users/{me['id']}", json=body)
            assert resp.status_code == 409, body
        # 自分自身は削除できない
        assert (await admin.delete(f"/api/auth/users/{me['id']}")).status_code == 400

        other = await _create(admin, "second-admin", "admin")
        # admin が 2 人いれば片方を降格できる
        assert (await admin.patch(f"/api/auth/users/{other['id']}", json={"role": "operator"})).status_code == 200
        assert (await admin.delete(f"/api/auth/users/{other['id']}")).status_code == 204


async def test_admin_password_reset_and_unlock(client: AsyncClient, open_client) -> None:
    user = await _create(client, "erin")
    async with open_client(None) as erin:
        await _login(erin, "erin")
        async with session_scope() as db:
            row = await db.get(User, uuid.UUID(user["id"]))
            assert row is not None
            row.locked_until = utcnow().replace(year=utcnow().year + 1)
        listed = next(u for u in (await client.get("/api/auth/users")).json() if u["username"] == "erin")
        assert listed["locked"] is True

        assert (await client.post(f"/api/auth/users/{user['id']}/unlock")).json()["locked"] is False

        resp = await client.post(
            f"/api/auth/users/{user['id']}/password", json={"password": "a fresh long password"}
        )
        assert resp.status_code == 204
        assert (await erin.get("/api/auth/me")).status_code == 401
        ok = await erin.post(
            "/api/auth/login", json={"username": "erin", "password": "a fresh long password"}
        )
        assert ok.status_code == 200


async def test_revoke_sessions(client: AsyncClient, open_client) -> None:
    user = await _create(client, "frank")
    async with open_client(None) as frank:
        await _login(frank, "frank")
        assert (await client.post(f"/api/auth/users/{user['id']}/sessions/revoke")).status_code == 204
        assert (await frank.get("/api/auth/me")).status_code == 401


async def test_directory_user_role_is_not_editable(client: AsyncClient) -> None:
    now = utcnow()
    async with session_scope() as db:
        row = User(
            realm_key="dir:00000000-0000-0000-0000-000000000001",
            subject="guid-1",
            username="ad-user",
            role="viewer",
            is_active=True,
            failed_login_count=0,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.flush()
        user_id = row.id
    resp = await client.patch(f"/api/auth/users/{user_id}", json={"role": "admin"})
    assert resp.status_code == 400
    reset = await client.post(f"/api/auth/users/{user_id}/password", json={"password": "whatever long pw"})
    assert reset.status_code == 400
    # 無効化はできる
    assert (await client.patch(f"/api/auth/users/{user_id}", json={"is_active": False})).status_code == 200


async def test_unknown_user_is_404(client: AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-00000000dead"
    assert (await client.patch(f"/api/auth/users/{missing}", json={})).status_code == 404
    assert (await client.delete(f"/api/auth/users/{missing}")).status_code == 404
