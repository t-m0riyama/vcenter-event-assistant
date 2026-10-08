"""ユーザー管理 API（admin のみ）。"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from httpx import AsyncClient
from sqlalchemy import select, update

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


async def test_concurrent_mutual_deletion_keeps_one_admin(open_client) -> None:
    """2 人の admin が同時に互いを削除しても、admin が 0 人にならない。"""
    async with open_client("admin", username="admin-a") as a, open_client("admin", username="admin-b") as b:
        users = {u["username"]: u["id"] for u in (await a.get("/api/auth/users")).json()}
        resp_a, resp_b = await asyncio.gather(
            a.delete(f"/api/auth/users/{users['admin-b']}"),
            b.delete(f"/api/auth/users/{users['admin-a']}"),
        )
    codes = sorted([resp_a.status_code, resp_b.status_code])
    # 先に確定した削除で相手のセッションが消えるため、後の要求は 401 か 409 になる
    assert codes[0] == 204 and codes[1] in (401, 409), codes
    async with session_scope() as db:
        admins = (await db.scalars(select(User).where(User.role == "admin"))).all()
        assert len(admins) == 1


async def test_concurrent_duplicate_create_is_400(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """事前確認をすり抜けた同名作成（一意制約違反）も 500 ではなく 400 にする。"""
    await _create(client, "race")

    async def not_found(db, username):
        return None

    monkeypatch.setattr("vcenter_event_assistant.auth.users.get_local_user", not_found)
    resp = await client.post(
        "/api/auth/users", json={"username": "RACE", "password": PASSWORD, "role": "viewer"}
    )
    assert resp.status_code == 400
    assert "既に存在" in resp.json()["detail"]


async def test_reactivation_revokes_sessions_left_from_before(client: AsyncClient, open_client) -> None:
    """無効化前のセッションが残っていても、再有効化で復活させない。"""
    user = await _create(client, "revive")
    async with open_client(None) as revive:
        await _login(revive, "revive")
        # セッションを残したまま無効化された状態（DB の直接操作などを想定）
        async with session_scope() as db:
            await db.execute(update(User).where(User.id == uuid.UUID(user["id"])).values(is_active=False))
        resp = await client.patch(f"/api/auth/users/{user['id']}", json={"is_active": True})
        assert resp.status_code == 200 and resp.json()["is_active"] is True
        assert (await revive.get("/api/auth/me")).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"display_name": "bad\x1bname"},
        {"email": "evil\x00@example.com"},
    ],
)
async def test_update_rejects_invalid_profile_fields(client: AsyncClient, body: dict) -> None:
    user = await _create(client, "profile")
    resp = await client.patch(f"/api/auth/users/{user['id']}", json=body)
    assert resp.status_code == 400
    async with session_scope() as db:
        row = await db.get(User, uuid.UUID(user["id"]))
        assert row is not None and row.display_name is None and row.email is None


async def test_update_trims_profile_fields(client: AsyncClient) -> None:
    user = await _create(client, "tidy")
    resp = await client.patch(
        f"/api/auth/users/{user['id']}", json={"display_name": "  Tidy User ", "email": "   "}
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Tidy User"
    assert resp.json()["email"] is None


async def test_create_rejects_control_characters_in_profile(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/users",
        json={"username": "ctl", "password": PASSWORD, "role": "viewer", "display_name": "a\x07b"},
    )
    assert resp.status_code == 400
