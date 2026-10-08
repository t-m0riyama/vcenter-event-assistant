"""AD / LDAP ディレクトリでの認証（ldap3 の MOCK_SYNC でディレクトリを模擬する）。"""

from __future__ import annotations

import ssl
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from ldap3 import MOCK_SYNC, Connection, Server
from sqlalchemy import select, text

from vcenter_event_assistant.auth.directory import backend, connection
from vcenter_event_assistant.auth.directory.connection import BindRejected, ConnectOptions
from vcenter_event_assistant.auth.directory.errors import (
    DirectoryAuthFailed,
    DirectoryConfigError,
    DirectoryMissingUniqueId,
    DirectoryNoRole,
    DirectoryUnavailable,
)
from vcenter_event_assistant.auth.directory.role_mapping import normalize_dn, resolve_role
from vcenter_event_assistant.auth.directory.spec import DirectorySpec
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.db.models import AuthSession, User
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.rate_limit import _rate_limiter
from vcenter_event_assistant.settings import Settings, get_settings

XHR = {"X-Requested-With": "XMLHttpRequest"}
BASE = "dc=example,dc=com"
SVC_DN = f"cn=svc,{BASE}"
ALICE_DN = f"uid=alice,ou=people,{BASE}"
BOB_DN = f"uid=bob,ou=people,{BASE}"
ADMINS = f"cn=Admins,ou=groups,{BASE}"
OPS = f"cn=Ops,ou=groups,{BASE}"
ALICE_CREDENTIALS = {"username": "alice", "password": "alice-secret"}


def _entries() -> dict[str, dict[str, Any]]:
    return {
        SVC_DN: {"userPassword": "svc-secret", "objectClass": "person"},
        ALICE_DN: {
            "userPassword": "alice-secret",
            "objectClass": ["inetOrgPerson"],
            "uid": "alice",
            "displayName": "Alice Liddell",
            "mail": "alice@example.com",
            "entryUUID": "6f1c-alice",
            "memberOf": [ADMINS],
        },
        BOB_DN: {
            "userPassword": "bob-secret",
            "objectClass": ["inetOrgPerson"],
            "uid": "bob",
            "entryUUID": "6f1c-bob",
            "memberOf": [],
        },
        ADMINS: {"objectClass": "groupOfNames", "member": [ALICE_DN]},
        OPS: {"objectClass": "groupOfNames", "member": [BOB_DN]},
        f"cn=posix-ops,ou=groups,{BASE}": {"objectClass": "posixGroup", "memberUid": ["bob"]},
    }


class FakeDirectory:
    """``connection.connect`` の代わりに MOCK_SYNC の接続を返す。"""

    def __init__(self) -> None:
        self.entries = _entries()
        self.binds: list[str | None] = []

    def connect(self, spec: DirectorySpec, *, user: str | None, password: str | None, options: ConnectOptions) -> Connection:
        connection.check_security(spec, options)
        if user is not None and not password:
            raise BindRejected("パスワードが空です。")
        conn = Connection(Server("mock"), user=user, password=password, client_strategy=MOCK_SYNC, raise_exceptions=False)
        for dn, attrs in self.entries.items():
            conn.strategy.add_entry(dn, dict(attrs))
        self.binds.append(user)
        if not conn.bind():
            raise BindRejected("資格情報が正しくありません。")
        return conn


@pytest.fixture
def directory(monkeypatch: pytest.MonkeyPatch) -> FakeDirectory:
    fake = FakeDirectory()
    monkeypatch.setattr(connection, "connect", fake.connect)
    return fake


def _spec(**overrides: Any) -> DirectorySpec:
    values: dict[str, Any] = dict(
        id=uuid.uuid4(),
        name="corp",
        kind="ldap",
        server_uris=("ldaps://ldap.example.com",),
        transport_security="ldaps",
        tls_verify=True,
        ca_cert_pem=None,
        bind_dn=SVC_DN,
        bind_password="svc-secret",
        timeout_seconds=5,
        user_search_base=BASE,
        user_search_filter=None,
        username_attribute="uid",
        ad_upn_suffix=None,
        display_name_attribute=None,
        email_attribute=None,
        group_mode="member_of",
        group_search_base=None,
        group_search_filter=None,
        group_member_attribute=None,
        group_member_value=None,
        mappings=((normalize_dn(ADMINS), Role.ADMIN), (normalize_dn(OPS), Role.OPERATOR)),
        mapping_labels=((ADMINS, Role.ADMIN), (OPS, Role.OPERATOR)),
    )
    values.update(overrides)
    return DirectorySpec(**values)


OPTIONS = ConnectOptions()


# --- フィルタと正規化 -------------------------------------------------------


def test_filters_escape_user_input() -> None:
    injected = "alice)(uid=*"
    assert backend.ldap_user_filter(_spec(), injected) == r"(uid=alice\29\28uid=\2a)"
    ad = backend.ad_user_filter("*)(sAMAccountName=admin", "example.com")
    assert "(sAMAccountName=\\2a\\29\\28sAMAccountName=admin)" in ad
    assert "*)(" not in ad
    assert backend.ad_in_chain_filter("cn=a*,dc=x") == r"(memberOf:1.2.840.113556.1.4.1941:=cn=a\2a,dc=x)"


def test_ad_filter_accepts_sam_upn_and_domain_prefix() -> None:
    f = backend.ad_user_filter("alice", "example.com")
    assert "(sAMAccountName=alice)" in f and "(userPrincipalName=alice@example.com)" in f
    # UPN で入力されたら UPN だけで探す（別ドメインの同名の sAMAccountName に広げない）
    f = backend.ad_user_filter("alice@corp.example.com", "example.com")
    assert "(userPrincipalName=alice@corp.example.com)" in f and "sAMAccountName" not in f
    # 無効化されたアカウントは除外する
    assert backend.AD_ENABLED_ACCOUNT_FILTER in f


def test_ldap_filter_template_requires_placeholder() -> None:
    spec = _spec(user_search_filter="(&(objectClass=person)(mail={username}))")
    assert backend.ldap_user_filter(spec, "a@b") == "(&(objectClass=person)(mail=a@b))"
    with pytest.raises(DirectoryConfigError):
        backend.ldap_user_filter(_spec(user_search_filter="(uid=fixed)"), "alice")


def test_normalize_dn_and_strongest_role() -> None:
    assert normalize_dn(" CN=Admins , OU=Groups,DC=Example,DC=com ") == normalize_dn(ADMINS)
    # 複数値 RDN（+）と RDN の区切り（,）は別の DN
    assert normalize_dn("cn=ops+uid=x,dc=example") != normalize_dn("cn=ops,uid=x,dc=example")
    assert normalize_dn("CN=Ops+UID=X,DC=Example") == "cn=ops+uid=x,dc=example"
    mappings = [(normalize_dn(OPS), Role.OPERATOR), (normalize_dn(ADMINS), Role.ADMIN)]
    assert resolve_role({normalize_dn(ADMINS), normalize_dn(OPS)}, mappings) == Role.ADMIN
    assert resolve_role({normalize_dn(OPS)}, mappings) == Role.OPERATOR
    assert resolve_role({"cn=other"}, mappings) is None


# --- TLS ---------------------------------------------------------------------


def test_tls_settings_follow_tls_verify() -> None:
    pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    verified = connection.build_tls(_spec(ca_cert_pem=pem))
    assert verified is not None
    assert verified.validate == ssl.CERT_REQUIRED and verified.ca_certs_data == pem
    insecure = connection.build_tls(_spec(tls_verify=False))
    assert insecure is not None and insecure.validate == ssl.CERT_NONE
    assert connection.build_tls(_spec(transport_security="none", server_uris=("ldap://x",))) is None


def test_insecure_tls_and_plaintext_can_be_forbidden() -> None:
    with pytest.raises(DirectoryConfigError, match="VEA_DIRECTORY_ALLOW_INSECURE_TLS"):
        connection.check_security(_spec(tls_verify=False), ConnectOptions(allow_insecure_tls=False))
    connection.check_security(_spec(tls_verify=False), ConnectOptions(allow_insecure_tls=True))
    with pytest.raises(DirectoryConfigError, match="本番環境"):
        connection.check_security(_spec(transport_security="none"), ConnectOptions(production=True))


def test_tls_failure_explains_the_cause() -> None:
    message = connection.describe_tls_failure(ssl.SSLError("certificate verify failed: self signed certificate"))
    assert "CA" in message and "証明書の検証を無効" in message
    assert "有効期限" in connection.describe_tls_failure(ssl.SSLError("certificate has expired"))
    assert "ホスト名" in connection.describe_tls_failure(ssl.SSLError("Hostname mismatch"))


# --- 認証の流れ ---------------------------------------------------------------


def test_ldap_member_of(directory: FakeDirectory) -> None:
    identity = backend.authenticate(_spec(), "alice", "alice-secret", OPTIONS)
    assert identity.role == Role.ADMIN
    assert identity.username == "alice"
    assert identity.display_name == "Alice Liddell" and identity.email == "alice@example.com"
    assert identity.subject == "uuid:6f1c-alice"
    # サービスアカウントで検索し、本人として bind する
    assert directory.binds == [SVC_DN, ALICE_DN]


def test_ldap_group_search_with_member_dn(directory: FakeDirectory) -> None:
    spec = _spec(
        group_mode="group_search",
        group_search_base=f"ou=groups,{BASE}",
        group_search_filter="(objectClass=groupOfNames)",
        group_member_attribute="member",
        group_member_value="dn",
    )
    assert backend.authenticate(spec, "bob", "bob-secret", OPTIONS).role == Role.OPERATOR


def test_ldap_group_search_with_posix_member_uid(directory: FakeDirectory) -> None:
    posix = f"cn=posix-ops,ou=groups,{BASE}"
    spec = _spec(
        group_mode="group_search",
        group_search_base=f"ou=groups,{BASE}",
        group_search_filter="(objectClass=posixGroup)",
        group_member_attribute="memberUid",
        group_member_value="username",
        mappings=((normalize_dn(posix), Role.VIEWER),),
        mapping_labels=((posix, Role.VIEWER),),
    )
    assert backend.authenticate(spec, "bob", "bob-secret", OPTIONS).role == Role.VIEWER


@pytest.mark.parametrize(
    ("username", "password", "reason"),
    [
        ("alice", "wrong", "bad_password"),
        ("nobody", "whatever", "unknown_user"),
        ("alice)(uid=*", "alice-secret", "unknown_user"),
    ],
)
def test_ldap_rejects_bad_credentials(directory: FakeDirectory, username: str, password: str, reason: str) -> None:
    with pytest.raises(DirectoryAuthFailed) as info:
        backend.authenticate(_spec(), username, password, OPTIONS)
    assert info.value.reason == reason


def test_empty_password_never_reaches_the_directory(directory: FakeDirectory) -> None:
    with pytest.raises(DirectoryAuthFailed):
        backend.authenticate(_spec(), "alice", "", OPTIONS)
    assert directory.binds == []


def test_ambiguous_user_is_rejected(directory: FakeDirectory) -> None:
    directory.entries[f"uid=alice,ou=other,{BASE}"] = {"userPassword": "x", "uid": "alice", "objectClass": "inetOrgPerson"}
    with pytest.raises(DirectoryAuthFailed) as info:
        backend.authenticate(_spec(), "alice", "alice-secret", OPTIONS)
    assert info.value.reason == "ambiguous_user"


def test_user_without_mapped_group_cannot_log_in(directory: FakeDirectory) -> None:
    with pytest.raises(DirectoryNoRole):
        backend.authenticate(_spec(), "bob", "bob-secret", OPTIONS)


CAROL_GUID = uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")


def test_ad_finds_users_by_sam_or_upn(directory: FakeDirectory) -> None:
    carol = f"cn=Carol,ou=people,{BASE}"
    directory.entries[carol] = {
        "userPassword": "carol-secret",
        "objectClass": ["user"],
        "objectCategory": "person",
        "sAMAccountName": "carol",
        "userPrincipalName": "carol@example.com",
        "msDS-PrincipalName": "CORP\\carol",
        "objectGUID": CAROL_GUID.bytes_le,
        "memberOf": [OPS],
    }
    spec = _spec(kind="ad", ad_upn_suffix="example.com", username_attribute=None)
    by_sam = backend.authenticate(spec, "CORP\\carol", "carol-secret", OPTIONS)
    by_upn = backend.authenticate(spec, "carol@example.com", "carol-secret", OPTIONS)
    assert by_sam.username == by_upn.username == "carol"
    # objectGUID で識別する（どちらの入力でも同じユーザー行になる）
    assert by_sam.subject == by_upn.subject == f"guid:{CAROL_GUID}"
    assert by_sam.role == Role.OPERATOR


def test_service_account_failure_is_unavailable(directory: FakeDirectory) -> None:
    from vcenter_event_assistant.auth.directory.errors import DirectoryUnavailable

    with pytest.raises(DirectoryUnavailable):
        backend.authenticate(_spec(bind_password="wrong"), "alice", "alice-secret", OPTIONS)


# --- API とログイン -------------------------------------------------------------


def _directory_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Corp LDAP",
        "kind": "ldap",
        "server_uris": ["ldaps://ldap.example.com"],
        "transport_security": "ldaps",
        "bind_dn": SVC_DN,
        "bind_password": "svc-secret",
        "user_search_base": BASE,
        "username_attribute": "uid",
        "group_mode": "member_of",
        "mappings": [{"group_dn": ADMINS, "role": "admin"}, {"group_dn": OPS, "role": "operator"}],
    }
    body.update(overrides)
    return body


def _raw_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def _dir_login(realm: str, username: str, password: str):
    _rate_limiter._hits.clear()
    async with _raw_client() as ac:
        resp = await ac.post(
            "/api/auth/login",
            json={"username": username, "password": password, "realm": realm},
            headers=XHR,
        )
        me = await ac.get("/api/auth/me") if resp.status_code == 200 else None
    return resp, me


async def test_directory_crud_hides_the_bind_password(client, monkeypatch: pytest.MonkeyPatch) -> None:
    # 暗号鍵があれば、サービスアカウントのパスワードは暗号化して保存する
    monkeypatch.setenv("VEA_SECRET_KEY", "directory-test-secret-key")
    get_settings.cache_clear()
    created = await client.post("/api/auth/directories", json=_directory_body())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["has_bind_password"] is True and "bind_password" not in body
    assert [m["role"] for m in body["mappings"]] == ["admin", "operator"]
    directory_id = body["id"]
    async with session_scope() as db:
        stored = await db.scalar(
            text("SELECT bind_password FROM directory_configs WHERE id = :id"),
            {"id": uuid.UUID(directory_id).hex},
        )
    assert stored and stored.startswith("enc:") and "svc-secret" not in stored

    # パスワードを省略した更新では保持し、clear_bind_password で消す
    kept = await client.patch(f"/api/auth/directories/{directory_id}", json={"sort_order": 3})
    assert kept.json()["has_bind_password"] is True and kept.json()["sort_order"] == 3
    cleared = await client.patch(
        f"/api/auth/directories/{directory_id}", json={"bind_dn": None, "clear_bind_password": True}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["has_bind_password"] is False and cleared.json()["bind_dn"] is None

    mappings = await client.patch(
        f"/api/auth/directories/{directory_id}",
        json={"mappings": [{"group_dn": OPS, "role": "viewer"}]},
    )
    assert mappings.json()["mappings"] == [{"group_dn": OPS, "role": "viewer"}]

    listed = await client.get("/api/auth/directories")
    assert [d["name"] for d in listed.json()] == ["Corp LDAP"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"server_uris": ["ldap://ldap.example.com"]}, "ldaps://"),
        ({"server_uris": ["ldaps://ldap.example.com/dc=example"]}, "パス"),
        ({"server_uris": ["ldaps://"]}, "ldaps://"),
        ({"server_uris": ["ldaps://ldap.example.com:99999"]}, "ldaps://"),
        ({"server_uris": ["ldaps://:secret@ldap.example.com"]}, "ldaps://"),
        ({"server_uris": ["ldaps://user:secret@ldap.example.com"]}, "ldaps://"),
        ({"bind_password": None}, "パスワード"),
        ({"user_search_filter": "(uid=fixed)"}, "{username}"),
        ({"group_mode": "group_search"}, "検索ベース"),
        ({"ca_cert_pem": "not a certificate"}, "PEM"),
        ({"name": "   "}, "名前"),
        ({"mappings": [{"group_dn": ADMINS, "role": "admin"}, {"group_dn": ADMINS.upper(), "role": "viewer"}]}, "重複"),
    ],
)
async def test_directory_validation(client, overrides: dict[str, Any], message: str) -> None:
    resp = await client.post("/api/auth/directories", json=_directory_body(**overrides))
    assert resp.status_code == 422
    assert message in resp.json()["detail"]


async def test_insecure_tls_is_refused_when_disallowed(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEA_DIRECTORY_ALLOW_INSECURE_TLS", "false")
    get_settings.cache_clear()
    resp = await client.post("/api/auth/directories", json=_directory_body(tls_verify=False))
    assert resp.status_code == 422
    assert "VEA_DIRECTORY_ALLOW_INSECURE_TLS" in resp.json()["detail"]


@pytest.mark.parametrize(
    ("production", "allow_insecure", "expected"),
    [
        (False, "true", {"allow_insecure_tls": True, "allow_no_transport_security": True}),
        (False, "false", {"allow_insecure_tls": False, "allow_no_transport_security": True}),
        (True, "true", {"allow_insecure_tls": True, "allow_no_transport_security": False}),
        (True, "false", {"allow_insecure_tls": False, "allow_no_transport_security": False}),
    ],
)
async def test_policy_reports_what_the_settings_allow(
    client, monkeypatch: pytest.MonkeyPatch, production: bool, allow_insecure: str, expected: dict[str, bool]
) -> None:
    # 画面が操作できない項目とその理由を出すための値。保存時の検証（_validate）と同じ設定から決まる
    monkeypatch.setenv("VEA_DIRECTORY_ALLOW_INSECURE_TLS", allow_insecure)
    get_settings.cache_clear()
    monkeypatch.setattr(Settings, "is_production", property(lambda self: production))
    resp = await client.get("/api/auth/directories/policy")
    assert resp.status_code == 200
    assert resp.json() == expected


async def test_insecure_tls_is_saved_with_a_warning(client, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="vcenter_event_assistant.audit"):
        resp = await client.post("/api/auth/directories", json=_directory_body(tls_verify=False))
    assert resp.status_code == 201 and resp.json()["tls_verify"] is False
    assert "directory_tls_verify_disabled" in caplog.text


async def test_directory_login_creates_and_updates_the_user(client, directory: FakeDirectory) -> None:
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"

    realms = (await client.get("/api/auth/realms")).json()["realms"]
    assert {"id": realm, "name": "Corp LDAP", "kind": "ldap"} in realms

    resp, me = await _dir_login(realm, "alice", "alice-secret")
    assert resp.status_code == 200, resp.text
    assert me is not None and me.json()["role"] == "admin" and me.json()["realm"] == realm
    assert me.json()["can_change_password"] is False

    # グループから外れると次のログインで拒否する。admin から operator に変われば、ロールも更新する
    directory.entries[ALICE_DN]["memberOf"] = []
    resp, _ = await _dir_login(realm, "alice", "alice-secret")
    assert resp.status_code == 401
    directory.entries[ALICE_DN]["memberOf"] = [OPS]
    resp, me = await _dir_login(realm, "alice", "alice-secret")
    assert resp.status_code == 200 and me is not None and me.json()["role"] == "operator"

    async with session_scope() as db:
        users = (await db.scalars(select(User).where(User.realm_key == realm))).all()
    assert [(u.username, u.role, u.display_name, u.password_hash) for u in users] == [
        ("alice", "operator", "Alice Liddell", None)
    ]


async def test_directory_login_respects_disabled_users_and_directories(client, directory: FakeDirectory) -> None:
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    assert (await _dir_login(realm, "alice", "alice-secret"))[0].status_code == 200

    # 管理画面で無効にしたユーザーは、ディレクトリで認証できてもログインさせない
    async with session_scope() as db:
        user = await db.scalar(select(User).where(User.realm_key == realm))
        assert user is not None
        user.is_active = False
    assert (await _dir_login(realm, "alice", "alice-secret"))[0].status_code == 401

    # 無効にしたディレクトリは一覧に出ず、ログインもできない
    resp = await client.patch(f"/api/auth/directories/{directory_id}", json={"is_enabled": False})
    assert resp.status_code == 200, resp.text
    assert realm not in [r["id"] for r in (await client.get("/api/auth/realms")).json()["realms"]]
    assert (await _dir_login(realm, "bob", "bob-secret"))[0].status_code == 401


async def test_disabling_a_directory_revokes_its_sessions_and_delete_needs_disable(client, directory: FakeDirectory) -> None:
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    resp, _ = await _dir_login(realm, "alice", "alice-secret")
    assert resp.status_code == 200

    assert (await client.delete(f"/api/auth/directories/{directory_id}")).status_code == 409
    assert (await client.patch(f"/api/auth/directories/{directory_id}", json={"is_enabled": False})).status_code == 200
    async with session_scope() as db:
        sessions = (await db.scalars(select(AuthSession).join(User).where(User.realm_key == realm))).all()
    assert sessions == []

    assert (await client.delete(f"/api/auth/directories/{directory_id}")).status_code == 204
    async with session_scope() as db:
        assert (await db.scalars(select(User).where(User.realm_key == realm))).all() == []
    assert (await client.get("/api/auth/directories")).json() == []


async def test_directory_cannot_be_disabled_when_it_provides_the_only_admin(open_client, directory: FakeDirectory) -> None:
    async with open_client("admin", username="local-admin") as admin:
        directory_id = (await admin.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    resp, _ = await _dir_login(realm, "alice", "alice-secret")
    assert resp.status_code == 200
    # ローカルの admin を降格すると、ログインできる admin はこのディレクトリの alice だけになる
    async with session_scope() as db:
        local = await db.scalar(select(User).where(User.username == "local-admin"))
        assert local is not None
        local.role = "viewer"
    _rate_limiter._hits.clear()
    async with _raw_client() as ac:
        await ac.post(
            "/api/auth/login",
            json={"username": "alice", "password": "alice-secret", "realm": realm},
            headers=XHR,
        )
        resp = await ac.patch(
            f"/api/auth/directories/{directory_id}", json={"is_enabled": False}, headers=XHR
        )
    assert resp.status_code == 409
    assert "管理者がいなくなります" in resp.json()["detail"]


async def test_connection_test_reports_each_stage(client, directory: FakeDirectory) -> None:
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    url = f"/api/auth/directories/{directory_id}/test"

    only_connect = (await client.post(url, json={})).json()
    assert only_connect["ok"] is True and [s["stage"] for s in only_connect["stages"]] == ["connect"]

    full = (await client.post(url, json={"username": "alice", "password": "alice-secret"})).json()
    assert full["ok"] is True
    assert [s["stage"] for s in full["stages"]] == ["connect", "user_search", "user_bind", "groups"]
    assert "admin" in full["stages"][-1]["message"] and ADMINS in full["stages"][-1]["message"]

    no_group = (await client.post(url, json={"username": "bob"})).json()
    assert no_group["ok"] is False and no_group["stages"][-1]["stage"] == "groups"

    bad_password = (await client.post(url, json={"username": "alice", "password": "nope"})).json()
    assert bad_password["ok"] is False and bad_password["stages"][-1]["stage"] == "user_bind"


def test_connect_tries_the_next_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """接続できないサーバは飛ばして次を試し、すべて失敗したら最後の理由を返す。"""
    from vcenter_event_assistant.auth.directory.errors import DirectoryUnavailable

    attempted: list[str] = []

    class _Conn:
        def __init__(self, server: Any, **_kw: Any) -> None:
            self.uri = server
            self.result: dict[str, Any] = {}

        def open(self) -> None:
            attempted.append(self.uri)
            raise OSError("connection refused")

        def unbind(self) -> None:
            pass

    monkeypatch.setattr(connection, "Connection", _Conn)
    monkeypatch.setattr(connection, "_server", lambda spec, uri: uri)
    spec = _spec(server_uris=("ldaps://a", "ldaps://b"))
    with pytest.raises(DirectoryUnavailable, match="ldaps://b"):
        connection.connect(spec, user=SVC_DN, password="x", options=OPTIONS)
    assert attempted == ["ldaps://a", "ldaps://b"]


class _ClosedSocketConn:
    """StartTLS の失敗でソケットが閉じた後の接続（実機の ldap3 と同じく unbind が送信に失敗する）。"""

    def __init__(self, server: Any, **_kw: Any) -> None:
        self.uri = server
        self.result: dict[str, Any] = {}

    def open(self) -> None:
        pass

    def start_tls(self) -> bool:
        if self.uri == "ldap://bad":
            from ldap3.core.exceptions import LDAPStartTLSError

            raise LDAPStartTLSError(
                "wrap socket error: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                "unable to get local issuer certificate"
            )
        return True

    def bind(self) -> bool:
        return True

    def unbind(self) -> None:
        from ldap3.core.exceptions import LDAPSocketSendError

        raise LDAPSocketSendError("socket sending error[Errno 9] Bad file descriptor")


def test_starttls_failure_explains_the_cause_and_tries_the_next_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """StartTLS の証明書エラーの後、閉じたソケットへの unbind の失敗で止まらない（実機の Samba / OpenLDAP で再現）。"""
    from vcenter_event_assistant.auth.directory.errors import DirectoryTlsError

    monkeypatch.setattr(connection, "Connection", _ClosedSocketConn)
    monkeypatch.setattr(connection, "_server", lambda spec, uri: uri)
    only_bad = _spec(transport_security="starttls", server_uris=("ldap://bad",))
    with pytest.raises(DirectoryTlsError, match="CA"):
        connection.connect(only_bad, user=SVC_DN, password="x", options=OPTIONS)

    failover = _spec(transport_security="starttls", server_uris=("ldap://bad", "ldap://good"))
    conn = connection.connect(failover, user=SVC_DN, password="x", options=OPTIONS)
    assert conn.uri == "ldap://good"


def test_plaintext_bind_refused_by_the_server_is_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """AD は暗号化しない接続での simple bind を strongerAuthRequired で断る。対処が分かるように伝える。"""

    class _Conn(_ClosedSocketConn):
        def bind(self) -> bool:
            self.result = {"description": "strongerAuthRequired"}
            return False

    monkeypatch.setattr(connection, "Connection", _Conn)
    monkeypatch.setattr(connection, "_server", lambda spec, uri: uri)
    spec = _spec(transport_security="none", server_uris=("ldap://dc",))
    with pytest.raises(DirectoryConfigError, match="LDAPS か StartTLS"):
        connection.connect(spec, user=SVC_DN, password="x", options=OPTIONS)


@pytest.fixture
def failing_unbind(directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch) -> None:
    """接続を閉じるときに、サーバ側で切断済みなどの理由で unbind が失敗する。"""
    from ldap3.core.exceptions import LDAPSocketSendError

    connect = directory.connect

    def _connect(*args: Any, **kwargs: Any) -> Connection:
        conn = connect(*args, **kwargs)

        def _unbind(*_a: Any, **_kw: Any) -> bool:
            raise LDAPSocketSendError("socket sending error[Errno 9] Bad file descriptor")

        conn.unbind = _unbind  # type: ignore[method-assign]
        return conn

    monkeypatch.setattr(connection, "connect", _connect)


@pytest.mark.usefixtures("failing_unbind")
def test_closing_errors_do_not_hide_the_result() -> None:
    """認証と接続試験の結果は、後始末の unbind の失敗で失われない。"""
    from vcenter_event_assistant.auth.directory.testing import run_test

    assert backend.authenticate(_spec(), "alice", "alice-secret", OPTIONS).role == Role.ADMIN
    stages = run_test(_spec(), OPTIONS, username="alice", password="alice-secret")
    assert all(stage.ok for stage in stages)


def test_long_subjects_are_hashed_not_truncated() -> None:
    from vcenter_event_assistant.auth.users import directory_subject_key

    prefix = "dn:" + "ou=x," * 120
    a, b = prefix + "cn=alice", prefix + "cn=bob"
    assert len(a) > 512
    assert directory_subject_key(a) != directory_subject_key(b)
    assert len(directory_subject_key(a)) <= 512 and directory_subject_key(a).startswith("sha256:")
    assert directory_subject_key("uuid:short") == "uuid:short"


def test_connection_test_uses_the_resolved_username(directory: FakeDirectory) -> None:
    """メールアドレスで検索しても、グループ（memberUid）は uid で調べる（本番のログインと同じ）。"""
    from vcenter_event_assistant.auth.directory.testing import run_test

    directory.entries[BOB_DN]["mail"] = "bob@example.com"
    posix = f"cn=posix-ops,ou=groups,{BASE}"
    spec = _spec(
        user_search_filter="(mail={username})",
        group_mode="group_search",
        group_search_base=f"ou=groups,{BASE}",
        group_search_filter="(objectClass=posixGroup)",
        group_member_attribute="memberUid",
        group_member_value="username",
        mappings=((normalize_dn(posix), Role.VIEWER),),
        mapping_labels=((posix, Role.VIEWER),),
    )
    stages = run_test(spec, OPTIONS, username="bob@example.com")
    assert stages[-1].stage == "groups" and stages[-1].ok, stages
    assert backend.authenticate(spec, "bob@example.com", "bob-secret", OPTIONS).role == Role.VIEWER



async def test_sessions_of_a_disabled_directory_stop_working(client, directory: FakeDirectory) -> None:
    """無効化と並行したログインが、無効化の後にセッションを作ってしまっても使えない。"""
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    _rate_limiter._hits.clear()
    async with _raw_client() as ac:
        assert (
            await ac.post(
                "/api/auth/login",
                json={"username": "alice", "password": "alice-secret", "realm": realm},
                headers=XHR,
            )
        ).status_code == 200
        # セッションの失効を経ずに、ディレクトリだけが無効になった状態
        from vcenter_event_assistant.db.models import DirectoryConfig

        async with session_scope() as db:
            config = await db.get(DirectoryConfig, uuid.UUID(directory_id))
            assert config is not None
            config.is_enabled = False
        assert (await ac.get("/api/auth/me")).status_code == 401


async def test_login_is_refused_if_the_directory_was_disabled_during_authentication(
    client, directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vcenter_event_assistant.auth import service
    from vcenter_event_assistant.db.models import DirectoryConfig

    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    original = service.run_directory_call

    async def disable_while_authenticating(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        async with session_scope() as db:
            config = await db.get(DirectoryConfig, uuid.UUID(directory_id))
            assert config is not None
            config.is_enabled = False
        return result

    monkeypatch.setattr(service, "run_directory_call", disable_while_authenticating)
    resp, _ = await _dir_login(f"dir:{directory_id}", "alice", "alice-secret")
    assert resp.status_code == 401
    async with session_scope() as db:
        users = (await db.scalars(select(User).where(User.realm_key == f"dir:{directory_id}"))).all()
    assert users == []


async def test_local_admins_do_not_count_when_local_login_is_disabled(
    client, directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    monkeypatch.setenv("VEA_LOCAL_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    resp = await client.patch(f"/api/auth/directories/{directory_id}", json={"is_enabled": False})
    assert resp.status_code == 409
    assert (await client.delete(f"/api/auth/directories/{directory_id}")).status_code == 409


async def test_removing_the_last_admin_mapping_is_guarded(
    client, directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    url = f"/api/auth/directories/{directory_id}"
    without_admin = {"mappings": [{"group_dn": OPS, "role": "operator"}]}

    # ローカルの admin がログインできる間は、admin の対応をなくしてもよい
    assert (await client.patch(url, json=without_admin)).status_code == 200
    assert (await client.patch(url, json={"mappings": [{"group_dn": ADMINS, "role": "admin"}]})).status_code == 200

    # ディレクトリ専用の運用では、唯一の admin の対応はなくせない（確認の資格情報を付けても同じ）
    monkeypatch.setenv("VEA_LOCAL_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    resp = await client.patch(url, json=without_admin)
    assert resp.status_code == 409 and "管理者" in resp.json()["detail"]
    resp = await client.patch(url, json={**without_admin, "verification": ALICE_CREDENTIALS})
    assert resp.status_code == 409 and "管理者" in resp.json()["detail"]
    # ほかに admin の対応を持つ有効なディレクトリがあればよい
    other = _directory_body(name="Other LDAP")
    assert (await client.post("/api/auth/directories", json=other)).status_code == 201
    assert (await client.patch(url, json=without_admin)).status_code == 200


def test_ad_domain_qualified_login_matches_the_domain(directory: FakeDirectory) -> None:
    """DOMAIN\\user では、別ドメインの同名アカウントを選ばない（あいまいにもしない）。"""
    for domain, ou in (("CORP", "corp"), ("LAB", "lab")):
        directory.entries[f"cn=Dave,ou={ou},{BASE}"] = {
            "userPassword": f"{ou}-secret",
            "objectClass": ["user"],
            "objectCategory": "person",
            "sAMAccountName": "dave",
            "msDS-PrincipalName": f"{domain}\\dave",
            "objectGUID": uuid.uuid4().bytes_le,
            "memberOf": [OPS],
        }
    spec = _spec(kind="ad", username_attribute=None)
    lab = backend.authenticate(spec, "lab\\dave", "lab-secret", OPTIONS)
    assert lab.dn == f"cn=Dave,ou=lab,{BASE}"
    # 別ドメインの名前では、そのドメインのアカウントのパスワードでも通らない
    with pytest.raises(DirectoryAuthFailed) as info:
        backend.authenticate(spec, "OTHER\\dave", "lab-secret", OPTIONS)
    assert info.value.reason == "unknown_user"
    # ドメインを付けない sAMAccountName だけでは 2 件に一致するので拒否する
    with pytest.raises(DirectoryAuthFailed) as info:
        backend.authenticate(spec, "dave", "lab-secret", OPTIONS)
    assert info.value.reason == "ambiguous_user"


async def test_stale_directory_admin_rows_do_not_protect_the_last_local_admin(client, directory: FakeDirectory) -> None:
    """無効にしたディレクトリに残る admin 行を数えて、唯一使えるローカル admin を降格させない。"""
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    resp, _ = await _dir_login(f"dir:{directory_id}", "alice", "alice-secret")
    assert resp.status_code == 200
    assert (await client.patch(f"/api/auth/directories/{directory_id}", json={"is_enabled": False})).status_code == 200

    users = (await client.get("/api/auth/users")).json()
    assert sorted(u["role"] for u in users) == ["admin", "admin"]  # ローカルと、無効にしたディレクトリの alice
    local_admin = next(u for u in users if u["is_local"])
    resp = await client.patch(f"/api/auth/users/{local_admin['id']}", json={"role": "viewer"})
    assert resp.status_code == 409
    # 使えない admin 行は、無効化しても使える admin は減らない
    stale = next(u for u in users if not u["is_local"])
    assert (await client.patch(f"/api/auth/users/{stale['id']}", json={"is_active": False})).status_code == 200


async def test_admin_mapping_counts_as_another_admin(client, directory: FakeDirectory) -> None:
    """admin の対応を持つ有効なディレクトリがあれば、その所属者が admin としてログインできるので、
    唯一のローカル admin でも降格できる（ディレクトリの admin は初回ログインまで行がない）。"""
    local_admin = next(u for u in (await client.get("/api/auth/users")).json() if u["is_local"])
    await client.post("/api/auth/directories", json=_directory_body())
    resp = await client.patch(f"/api/auth/users/{local_admin['id']}", json={"role": "viewer"})
    assert resp.status_code == 200, resp.text


def test_server_reads_host_port_and_ssl_from_the_uri() -> None:
    """ldap3 の Server は ldap(s):// の URI からホスト・ポート・SSL を読み取る。"""
    server = connection._server(_spec(), "ldaps://dc1.example.com:1636")
    assert (server.host, server.port, server.ssl) == ("dc1.example.com", 1636, True)
    server = connection._server(_spec(), "ldaps://dc1.example.com")
    assert (server.host, server.port, server.ssl) == ("dc1.example.com", 636, True)
    plain = _spec(transport_security="starttls", server_uris=("ldap://dc1.example.com",))
    server = connection._server(plain, "ldap://dc1.example.com")
    assert (server.host, server.port, server.ssl) == ("dc1.example.com", 389, False)


async def test_changing_mappings_revokes_directory_sessions(client, directory: FakeDirectory) -> None:
    """対応表を変えたら、ログイン中のディレクトリのユーザーは失効させ、次のログインで決め直す。"""
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    _rate_limiter._hits.clear()
    async with _raw_client() as ac:
        await ac.post(
            "/api/auth/login",
            json={"username": "alice", "password": "alice-secret", "realm": realm},
            headers=XHR,
        )
        assert (await ac.get("/api/auth/me")).json()["role"] == "admin"
        resp = await client.patch(
            f"/api/auth/directories/{directory_id}",
            json={"mappings": [{"group_dn": ADMINS, "role": "viewer"}]},
        )
        assert resp.status_code == 200
        assert (await ac.get("/api/auth/me")).status_code == 401
    resp, me = await _dir_login(realm, "alice", "alice-secret")
    assert resp.status_code == 200 and me is not None and me.json()["role"] == "viewer"



def test_normalize_dn_keeps_case_of_case_sensitive_attributes() -> None:
    """値をならすのは大文字小文字を区別しない属性だけ。それ以外の属性の値は区別したまま比べる。"""
    assert normalize_dn("CN=Ops,OU=Groups,DC=Example") == normalize_dn("cn=ops,ou=groups,dc=example")
    assert normalize_dn("customId=Ops,dc=example") != normalize_dn("customId=ops,dc=example")
    assert normalize_dn("CUSTOMID=Ops,dc=example") == normalize_dn("customId=Ops,DC=EXAMPLE")


async def test_login_is_refused_if_the_mappings_changed_during_authentication(
    client, directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """認証中に対応表が置き換わったら、古い対応表で決めたロールのセッションを作らない。"""
    from vcenter_event_assistant.auth import service

    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    original = service.run_directory_call

    async def replace_while_authenticating(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        resp = await client.patch(
            f"/api/auth/directories/{directory_id}",
            json={"mappings": [{"group_dn": ADMINS, "role": "viewer"}]},
        )
        assert resp.status_code == 200
        return result

    monkeypatch.setattr(service, "run_directory_call", replace_while_authenticating)
    resp, _ = await _dir_login(f"dir:{directory_id}", "alice", "alice-secret")
    assert resp.status_code == 401
    monkeypatch.setattr(service, "run_directory_call", original)
    resp, me = await _dir_login(f"dir:{directory_id}", "alice", "alice-secret")
    assert resp.status_code == 200 and me is not None and me.json()["role"] == "viewer"


async def test_identity_changes_revoke_directory_sessions(client, directory: FakeDirectory) -> None:
    """接続先や検索条件を変えたらログイン中のセッションを失効させ、名前や表示順だけの変更では保つ。"""
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    _rate_limiter._hits.clear()
    async with _raw_client() as ac:
        await ac.post(
            "/api/auth/login",
            json={"username": "alice", "password": "alice-secret", "realm": realm},
            headers=XHR,
        )
        assert (await ac.get("/api/auth/me")).status_code == 200
        resp = await client.patch(
            f"/api/auth/directories/{directory_id}", json={"name": "Renamed", "sort_order": 5}
        )
        assert resp.status_code == 200
        assert (await ac.get("/api/auth/me")).status_code == 200
        resp = await client.patch(
            f"/api/auth/directories/{directory_id}", json={"user_search_base": "ou=Other,dc=example,dc=com"}
        )
        assert resp.status_code == 200
        assert (await ac.get("/api/auth/me")).status_code == 401


def test_normalize_dn_ignores_ava_order_within_an_rdn() -> None:
    """複数値 RDN の中の順序は区別しない。RDN の間の順序と ``+`` / ``,`` の違いは区別する。"""
    assert normalize_dn("uid=x+cn=ops,dc=example") == normalize_dn("CN=Ops+UID=X,DC=Example")
    assert normalize_dn("cn=ops+uid=x,dc=example") != normalize_dn("cn=ops,uid=x,dc=example")
    assert normalize_dn("cn=ops,ou=a,dc=example") != normalize_dn("ou=a,cn=ops,dc=example")


async def test_bind_password_with_storage_prefix_is_rejected(client, directory: FakeDirectory) -> None:
    """``enc:`` で始まる bind パスワードは暗号化されずに保存されてしまうため受け付けない。"""
    resp = await client.post("/api/auth/directories", json=_directory_body(bind_password="enc:secret"))
    assert resp.status_code == 422
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    resp = await client.patch(f"/api/auth/directories/{directory_id}", json={"bind_password": "enc:secret"})
    assert resp.status_code == 422


async def test_malformed_group_dn_is_rejected(client, directory: FakeDirectory) -> None:
    """DN として解析できない値は、どのグループとも一致しないので対応表に登録させない。"""
    body = _directory_body(mappings=[{"group_dn": "not a DN", "role": "admin"}])
    assert (await client.post("/api/auth/directories", json=body)).status_code == 422
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    resp = await client.patch(
        f"/api/auth/directories/{directory_id}",
        json={"mappings": [{"group_dn": "not a DN", "role": "admin"}]},
    )
    assert resp.status_code == 422


class _TruncatingConnection:
    """サーバ側の件数上限で、指定より少ない件数で sizeLimitExceeded を返す接続。"""

    def __init__(self, count: int) -> None:
        self.count = count
        self.response: list[dict[str, Any]] = []
        self.result: dict[str, Any] = {}

    def search(self, base: str, search_filter: str, **kwargs: Any) -> bool:
        self.response = [
            {"type": "searchResEntry", "dn": f"cn=u{i},{base}", "attributes": {}, "raw_attributes": {}}
            for i in range(self.count)
        ]
        self.result = {"result": 4, "description": "sizeLimitExceeded"}
        return True


def test_user_search_truncated_by_the_server_is_not_treated_as_unique() -> None:
    """サーバの件数上限で 1 件だけ返った結果から、一意と判断して認証しない。"""
    with pytest.raises(DirectoryUnavailable):
        backend.find_user(_TruncatingConnection(1), _spec(), "alice")  # type: ignore[arg-type]
    # 指定した件数（2 件）まで取れたなら、複数見つかったとして扱う
    with pytest.raises(DirectoryAuthFailed):
        backend.find_user(_TruncatingConnection(2), _spec(), "alice")  # type: ignore[arg-type]


def test_too_many_domain_qualified_candidates_are_ambiguous() -> None:
    """``DOMAIN\\user`` の候補が上限に達したら、残りを確かめられないので一意とみなさない。"""
    conn = _TruncatingConnection(backend.AD_QUALIFIED_CANDIDATES_LIMIT + 1)
    spec = _spec(kind="ad", group_mode="ad_nested")
    with pytest.raises(DirectoryAuthFailed) as exc:
        backend.find_user(conn, spec, "CORP\\alice")  # type: ignore[arg-type]
    assert exc.value.reason == "ambiguous_user"


async def test_blank_search_base_is_rejected_on_create(client, directory: FakeDirectory) -> None:
    resp = await client.post("/api/auth/directories", json=_directory_body(user_search_base="   "))
    assert resp.status_code == 422


async def test_policy_blocked_directory_does_not_count_as_an_admin_source(
    client, directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """今の設定で接続を拒否されるディレクトリ（証明書を検証しない接続の禁止など）は、admin の手段に数えない。"""
    local_admin = next(u for u in (await client.get("/api/auth/users")).json() if u["is_local"])
    resp = await client.post("/api/auth/directories", json=_directory_body(tls_verify=False))
    assert resp.status_code == 201, resp.text
    monkeypatch.setenv("VEA_DIRECTORY_ALLOW_INSECURE_TLS", "false")
    get_settings.cache_clear()
    resp = await client.patch(f"/api/auth/users/{local_admin['id']}", json={"role": "viewer"})
    assert resp.status_code == 409


async def test_directory_users_cannot_be_deleted(client, directory: FakeDirectory) -> None:
    """ディレクトリのユーザーは消しても次のログインで作り直されるので、削除ではなく無効化させる。"""
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    resp, _ = await _dir_login(realm, "alice", "alice-secret")
    assert resp.status_code == 200
    alice = next(u for u in (await client.get("/api/auth/users")).json() if u["username"] == "alice")
    assert (await client.delete(f"/api/auth/users/{alice['id']}")).status_code == 422
    assert (await client.patch(f"/api/auth/users/{alice['id']}", json={"is_active": False})).status_code == 200
    resp, _ = await _dir_login(realm, "alice", "alice-secret")
    assert resp.status_code == 401


@pytest.mark.parametrize(("password", "ok"), [("あ" * 341 + "a", True), ("あ" * 342, False)])
async def test_bind_password_is_limited_by_utf8_bytes(
    client, directory: FakeDirectory, password: str, ok: bool
) -> None:
    """暗号化後に列の長さを超えないよう、bind パスワードは UTF-8 のバイト数で制限する。"""
    resp = await client.post("/api/auth/directories", json=_directory_body(bind_password=password))
    assert (resp.status_code == 201) is ok, resp.text


class _QualifiedCandidates:
    """sAMAccountName が同じアカウントを ``count`` 件（完全な結果として）返し、msDS-PrincipalName も返す接続。"""

    def __init__(self, count: int) -> None:
        self.count = count
        self.response: list[dict[str, Any]] = []
        self.result: dict[str, Any] = {}

    def search(self, base: str, search_filter: str, *, search_scope: Any = None, **kwargs: Any) -> bool:
        if search_filter == "(objectClass=*)":
            domain = "CORP" if base.startswith("cn=u0,") else f"D{base.split(',')[0]}"
            self.response = [
                {
                    "type": "searchResEntry",
                    "dn": base,
                    "attributes": {"msDS-PrincipalName": f"{domain}\\alice"},
                    "raw_attributes": {},
                }
            ]
        else:
            self.response = [
                {"type": "searchResEntry", "dn": f"cn=u{i},{base}", "attributes": {}, "raw_attributes": {}}
                for i in range(self.count)
            ]
        self.result = {"result": 0, "description": "success"}
        return True


def test_domain_qualified_candidates_exactly_at_the_limit_are_resolved() -> None:
    """候補がちょうど上限の件数で、検索が完全に終わっていれば、msDS-PrincipalName で絞り込める。"""
    conn = _QualifiedCandidates(backend.AD_QUALIFIED_CANDIDATES_LIMIT)
    spec = _spec(kind="ad", group_mode="ad_nested")
    entry = backend.find_user(conn, spec, "CORP\\alice")  # type: ignore[arg-type]
    assert entry.dn.startswith("cn=u0,")


async def test_group_dn_too_long_after_normalization_is_rejected(client, directory: FakeDirectory) -> None:
    """正規化（NFKC・casefold）で列の長さを超える DN は、DB エラーではなく 422 にする。"""
    group_dn = "cn=" + "\ufdfa" * 100 + ",dc=example"
    assert len(group_dn) <= 1024 and len(normalize_dn(group_dn)) > 1024
    body = _directory_body(mappings=[{"group_dn": group_dn, "role": "admin"}])
    assert (await client.post("/api/auth/directories", json=body)).status_code == 422



def test_normalize_dn_treats_attribute_oids_as_their_names() -> None:
    """属性を OID で書いた DN も、名前で書いた DN と同じものとして扱う。"""
    expected = normalize_dn("CN=Admins,OU=Groups,DC=Example,DC=com")
    assert normalize_dn("2.5.4.3=Admins,2.5.4.11=Groups,0.9.2342.19200300.100.1.25=Example,dc=com") == expected
    assert normalize_dn("OID.2.5.4.3=Admins,ou=Groups,dc=example,dc=com") == expected


def test_oid_replacement_ignores_escaped_separators() -> None:
    """値の中（エスケープした区切りの後や引用符の中）の OID らしい文字列は置き換えず、別の DN と区別する。"""
    from vcenter_event_assistant.auth.directory.role_mapping import _replace_known_oids

    assert _replace_known_oids(r"cn=foo\,2.5.4.3=bar,dc=example") == r"cn=foo\,2.5.4.3=bar,dc=example"
    assert _replace_known_oids("2.5.4.3=a+OID.2.5.4.11=b,dc=x") == "cn=a+ou=b,dc=x"
    assert normalize_dn(r"cn=foo\,2.5.4.3=bar,dc=example") != normalize_dn(r"cn=foo\,cn=bar,dc=example")
    assert normalize_dn('cn="a,2.5.4.3=b",dc=x') != normalize_dn('cn="a,cn=b",dc=x')
    # バックスラッシュ自体をエスケープした後の区切りは本物なので、その後の OID は置き換える
    assert normalize_dn(r"cn=a\\,2.5.4.3=b,dc=x") == normalize_dn(r"cn=a\\,cn=b,dc=x")


def test_normalize_dn_treats_escape_notations_alike() -> None:
    """同じ文字のエスケープ表記の違い（``\\,`` と ``\\2C``、16 進の大文字小文字、UTF-8 のバイト列）をならす。"""
    expected = normalize_dn(r"cn=Ops\,EMEA,ou=Groups,dc=example")
    assert normalize_dn(r"cn=Ops\2CEMEA,ou=Groups,dc=example") == expected
    assert normalize_dn(r"cn=Ops\2cEMEA,ou=Groups,dc=example") == expected
    assert normalize_dn(r"cn=Caf\C3\A9,dc=example") == normalize_dn("cn=Café,dc=example")
    assert normalize_dn(r"cn=a\20b,dc=example") == normalize_dn("cn=a b,dc=example")
    # 戻した文字が区切りでも、本物の区切りとは区別する
    assert normalize_dn(r"cn=a\2Bb=c,dc=example") != normalize_dn("cn=a+b=c,dc=example")
    assert normalize_dn(r"cn=a\2Cdc=example") != normalize_dn("cn=a,dc=example")
    # 大文字小文字を区別する属性では、エスケープした先頭の空白は値の一部
    assert normalize_dn(r"customId=\20ops,dc=example") == normalize_dn(r"customId=\ ops,dc=example")
    assert normalize_dn(r"customId=\20ops,dc=example") != normalize_dn("customId=ops,dc=example")


def test_group_dn_with_invalid_escape_is_not_valid() -> None:
    """UTF-8 として戻せないエスケープや不正なエスケープは、解析できない DN として扱う。"""
    from vcenter_event_assistant.auth.directory.role_mapping import is_valid_dn

    assert is_valid_dn(r"cn=Caf\C3\A9,dc=example")
    assert not is_valid_dn(r"cn=Caf\C3,dc=example")
    assert not is_valid_dn(r"cn=Ops\ZZ,dc=example")


async def test_login_is_refused_if_the_user_was_disabled_while_updating(client, directory: FakeDirectory) -> None:
    """ユーザー行を読んでから更新するまでの間に無効化されたら、ログインさせない（Cookie を返さない）。"""
    from sqlalchemy import event, update
    from sqlalchemy.orm import Session

    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    assert (await _dir_login(realm, "alice", "alice-secret"))[0].status_code == 200

    def disable_before_update(session: Session, _context: Any, _instances: Any) -> None:
        # 管理者による無効化を、ログイン側がユーザー行を読んだ後・更新する前に割り込ませる
        for obj in session.dirty:
            if isinstance(obj, User) and obj.realm_key == realm:
                session.connection().execute(update(User).where(User.id == obj.id).values(is_active=False))

    async with session_scope() as db:
        sessions_before = len((await db.scalars(select(AuthSession))).all())
        last_login_before = await db.scalar(select(User.last_login_at).where(User.realm_key == realm))
    event.listen(Session, "before_flush", disable_before_update)
    try:
        resp, me = await _dir_login(realm, "alice", "alice-secret")
    finally:
        event.remove(Session, "before_flush", disable_before_update)
    assert resp.status_code == 401 and me is None
    assert "set-cookie" not in resp.headers
    async with session_scope() as db:
        assert len((await db.scalars(select(AuthSession))).all()) == sessions_before
        # ログイン側の更新も取り消す（割り込ませた無効化は同じセーブポイントの中なので一緒に巻き戻る）
        assert await db.scalar(select(User.last_login_at).where(User.realm_key == realm)) == last_login_before


def test_normalize_dn_ignores_insignificant_spaces_of_case_ignore_attributes() -> None:
    """caseIgnoreMatch の属性（cn など）では、連続する空白と前後の空白は比較に影響しない（RFC 4518）。"""
    assert normalize_dn("cn=Ops  Team,dc=example") == normalize_dn("cn=Ops Team,dc=example")
    assert normalize_dn(r"cn=\20Ops Team\20,dc=example") == normalize_dn("cn=Ops Team,dc=example")
    assert normalize_dn("cn=OpsTeam,dc=example") != normalize_dn("cn=Ops Team,dc=example")
    # 大文字小文字を区別する属性の空白はならさない
    assert normalize_dn("customId=Ops  Team,dc=example") != normalize_dn("customId=Ops Team,dc=example")


async def test_concurrent_duplicate_directory_name_is_rejected(client, directory: FakeDirectory) -> None:
    """名前の確認の後に同じ名前が確定しても（並行した作成・変更）、500 ではなく 422 にする。"""
    from sqlalchemy import event, update
    from sqlalchemy.orm import Session

    from vcenter_event_assistant.db.models import DirectoryConfig

    other = (await client.post("/api/auth/directories", json=_directory_body(name="Other"))).json()["id"]
    target = {"name": ""}

    def take_name_before_flush(session: Session, _context: Any, _instances: Any) -> None:
        # 並行したリクエストが、名前の確認の後・こちらの書き込みの前に同じ名前を確定させた状態を作る
        if any(isinstance(obj, DirectoryConfig) for obj in (*session.new, *session.dirty)):
            session.connection().execute(
                update(DirectoryConfig).where(DirectoryConfig.id == uuid.UUID(other)).values(name=target["name"])
            )

    event.listen(Session, "before_flush", take_name_before_flush)
    try:
        target["name"] = "Corp LDAP"
        created = await client.post("/api/auth/directories", json=_directory_body(name="Corp LDAP"))
    finally:
        event.remove(Session, "before_flush", take_name_before_flush)
    assert created.status_code == 422, created.text
    assert "同じ名前" in created.json()["detail"]

    # 名前の変更でも同じ
    directory_id = (await client.post("/api/auth/directories", json=_directory_body(name="Third"))).json()["id"]
    event.listen(Session, "before_flush", take_name_before_flush)
    try:
        target["name"] = "Renamed"
        renamed = await client.patch(f"/api/auth/directories/{directory_id}", json={"name": "Renamed"})
    finally:
        event.remove(Session, "before_flush", take_name_before_flush)
    assert renamed.status_code == 422, renamed.text
    assert "同じ名前" in renamed.json()["detail"]

    # 名前と一緒に認証に関わる設定を変えても（途中でセッションの失効のために書き込んでも）同じ
    event.listen(Session, "before_flush", take_name_before_flush)
    try:
        target["name"] = "Renamed again"
        renamed = await client.patch(
            f"/api/auth/directories/{directory_id}",
            json={"name": "Renamed again", "user_search_base": "ou=people,dc=example,dc=org"},
        )
    finally:
        event.remove(Session, "before_flush", take_name_before_flush)
    assert renamed.status_code == 422, renamed.text
    assert "同じ名前" in renamed.json()["detail"]


async def test_directory_sessions_are_revoked_with_one_delete(client, directory: FakeDirectory) -> None:
    """設定の変更でセッションを失効させるとき、ユーザーの数によらず DELETE は 1 回で済ませる。"""
    from sqlalchemy import event

    from vcenter_event_assistant.db.session import get_engine

    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    assert (await _dir_login(realm, "alice", "alice-secret"))[0].status_code == 200
    async with session_scope() as db:
        for i in range(5):
            db.add(User(realm_key=realm, subject=f"uuid:extra-{i}", username=f"extra{i}", role="viewer",
                        directory_id=uuid.UUID(directory_id), is_active=True, failed_login_count=0))

    deletes: list[str] = []

    def count_session_deletes(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if statement.lstrip().upper().startswith("DELETE FROM AUTH_SESSIONS"):
            deletes.append(statement)

    engine = get_engine().sync_engine
    event.listen(engine, "before_cursor_execute", count_session_deletes)
    try:
        # 設定と対応表を同時に変えても、失効は 1 回にまとめる
        resp = await client.patch(
            f"/api/auth/directories/{directory_id}",
            json={"user_search_filter": "(uid={username})", "mappings": [{"group_dn": ADMINS, "role": "admin"}]},
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_session_deletes)
    assert resp.status_code == 200, resp.text
    assert len(deletes) == 1
    async with session_scope() as db:
        users = select(User.id).where(User.realm_key == realm)
        assert (await db.scalars(select(AuthSession).where(AuthSession.user_id.in_(users)))).all() == []


def test_normalize_dn_folds_case_of_other_standard_case_ignore_attributes() -> None:
    """cn・ou 以外の標準の命名属性（sn・givenName など）も大文字小文字を区別せずに比べる。"""
    assert normalize_dn("sn=Ops,dc=example") == normalize_dn("SN=ops,dc=example")
    assert normalize_dn("givenName=Ops,dc=example") == normalize_dn("2.5.4.42=ops,dc=example")
    assert normalize_dn("mail=Ops@Example.com,dc=example") == normalize_dn("mail=ops@example.com,dc=example")


async def test_sessions_of_directories_blocked_by_policy_stop_working(
    client, directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """接続の方針（証明書を検証しない接続の禁止など）で拒否されるディレクトリの発行済みセッションも使わせない。"""
    body = _directory_body(tls_verify=False)
    directory_id = (await client.post("/api/auth/directories", json=body)).json()["id"]
    realm = f"dir:{directory_id}"
    _rate_limiter._hits.clear()
    async with _raw_client() as ac:
        resp = await ac.post(
            "/api/auth/login", json={"username": "alice", "password": "alice-secret", "realm": realm}, headers=XHR
        )
        assert resp.status_code == 200
        assert (await ac.get("/api/auth/me")).status_code == 200

        monkeypatch.setenv("VEA_DIRECTORY_ALLOW_INSECURE_TLS", "false")
        get_settings.cache_clear()
        assert (await ac.get("/api/auth/me")).status_code == 401
        # ログイン画面の認証先にも出さない（選んでも必ず失敗するため）
        assert realm not in [r["id"] for r in (await ac.get("/api/auth/realms")).json()["realms"]]


def test_normalize_dn_applies_unicode_normalization_to_case_ignore_values() -> None:
    """caseIgnoreMatch の値は Unicode の正規化（NFKC）をしてから比べる（合成済みの文字と分解した文字は同じ）。"""
    composed = "cn=Caf\u00e9,dc=example"
    decomposed = "cn=Cafe\u0301,dc=example"
    assert normalize_dn(composed) == normalize_dn(decomposed)
    assert normalize_dn("cn=\uff2f\uff50\uff53,dc=example") == normalize_dn("cn=Ops,dc=example")  # 全角


def test_normalize_dn_covers_all_rfc4519_case_ignore_attributes() -> None:
    """RFC 4519 で caseIgnoreMatch と定義された属性は、どれも大文字小文字を区別せずに比べる。"""
    for attr, oid in (
        ("name", "2.5.4.41"),
        ("postalCode", "2.5.4.17"),
        ("postOfficeBox", "2.5.4.18"),
        ("physicalDeliveryOfficeName", "2.5.4.19"),
        ("destinationIndicator", "2.5.4.27"),
        ("knowledgeInformation", "2.5.4.2"),
    ):
        assert normalize_dn(f"{attr}=Ops,dc=example") == normalize_dn(f"{attr.upper()}=ops,DC=example"), attr
        assert normalize_dn(f"{oid}=Ops,dc=example") == normalize_dn(f"{attr}=ops,dc=example"), attr


def test_normalize_dn_covers_rfc4524_case_ignore_attributes() -> None:
    """RFC 4524（COSINE）で caseIgnoreMatch / caseIgnoreIA5Match と定義された属性も、大文字小文字を区別しない。"""
    for attr, oid in (
        ("roomNumber", "0.9.2342.19200300.100.1.6"),
        ("buildingName", "0.9.2342.19200300.100.1.48"),
        ("co", "0.9.2342.19200300.100.1.43"),
        ("organizationalStatus", "0.9.2342.19200300.100.1.45"),
        ("personalTitle", "0.9.2342.19200300.100.1.40"),
        ("uniqueIdentifier", "0.9.2342.19200300.100.1.44"),
        ("userClass", "0.9.2342.19200300.100.1.8"),
        ("associatedDomain", "0.9.2342.19200300.100.1.37"),
    ):
        assert normalize_dn(f"{attr}=Ops,dc=example") == normalize_dn(f"{attr.upper()}=ops,DC=example"), attr
        assert normalize_dn(f"{oid}=Ops,dc=example") == normalize_dn(f"{attr}=ops,dc=example"), attr


async def test_directory_role_change_on_login_revokes_other_sessions(client, directory: FakeDirectory) -> None:
    """ログインでグループから決まるロールが変わったら、そのユーザーの他のセッションを失効させる。

    ロールは毎リクエストでユーザー行から読むので、残すと古い Cookie が新しいロールで使えてしまう。
    """
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    login = {"username": "alice", "password": "alice-secret", "realm": realm}
    async with _raw_client() as first, _raw_client() as second, _raw_client() as third:
        _rate_limiter._hits.clear()
        assert (await first.post("/api/auth/login", json=login, headers=XHR)).status_code == 200
        # 同じロールのままなら、別の端末のログインで既存のセッションは消さない
        assert (await second.post("/api/auth/login", json=login, headers=XHR)).status_code == 200
        assert (await first.get("/api/auth/me")).json()["role"] == "admin"

        directory.entries[ALICE_DN]["memberOf"] = [OPS]
        assert (await third.post("/api/auth/login", json=login, headers=XHR)).status_code == 200
        assert (await third.get("/api/auth/me")).json()["role"] == "operator"
        assert (await first.get("/api/auth/me")).status_code == 401
        assert (await second.get("/api/auth/me")).status_code == 401


async def test_directory_login_locks_the_user_row_before_comparing_roles(client, directory: FakeDirectory) -> None:
    """ディレクトリのログインは、ユーザー行を FOR UPDATE で読んでからロールを比べる（#255）。

    ロックせずに読むと、PostgreSQL では同じユーザーの並行したログインのセッション（未確定）の失効が漏れる。
    SQLite は FOR UPDATE を SQL に出さず、競合も再現できないので、ORM の文を PostgreSQL の方言で確かめる。
    """
    from sqlalchemy import event
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session

    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    assert (await _dir_login(realm, "alice", "alice-secret"))[0].status_code == 200

    user_selects: list[str] = []

    def capture(state: Any) -> None:
        if state.is_select and any(m.class_ is User for m in state.all_mappers):
            user_selects.append(str(state.statement.compile(dialect=postgresql.dialect())))

    event.listen(Session, "do_orm_execute", capture)
    try:
        directory.entries[ALICE_DN]["memberOf"] = [OPS]
        assert (await _dir_login(realm, "alice", "alice-secret"))[0].status_code == 200
    finally:
        event.remove(Session, "do_orm_execute", capture)
    lookups = [sql for sql in user_selects if "users.subject = " in sql]
    assert lookups, user_selects
    assert all(sql.rstrip().endswith("FOR UPDATE") for sql in lookups), lookups


class _MissingBaseConnection:
    """検索ベースが存在しない（noSuchObject）と返す接続。"""

    def __init__(self) -> None:
        self.response: list[dict[str, Any]] = []
        self.result: dict[str, Any] = {}

    def search(self, base: str, search_filter: str, **kwargs: Any) -> bool:
        self.response = []
        self.result = {"result": 32, "description": "noSuchObject"}
        return False


def test_missing_search_base_is_a_directory_error() -> None:
    """検索ベースがないのは設定の誤りなので、ユーザーが見つからないのとは区別する（運用者に警告が出る）。"""
    with pytest.raises(DirectoryConfigError, match="検索の起点"):
        backend.find_user(_MissingBaseConnection(), _spec(), "alice")  # type: ignore[arg-type]


# --- ユーザーの ID（subject）。DN は変わり得るので使わない（#253） ----------------------


def test_ldap_user_without_unique_id_is_refused(directory: FakeDirectory) -> None:
    """entryUUID が取れないユーザーは、DN を ID の代わりにせずログインを拒否する。"""
    del directory.entries[ALICE_DN]["entryUUID"]
    with pytest.raises(DirectoryMissingUniqueId) as info:
        backend.authenticate(_spec(), "alice", "alice-secret", OPTIONS)
    # 接続・設定の問題として運用者に警告が出る理由にする
    assert info.value.reason.startswith("directory_")


def test_ad_user_without_object_guid_is_refused(directory: FakeDirectory) -> None:
    directory.entries[f"cn=Erin,ou=people,{BASE}"] = {
        "userPassword": "erin-secret",
        "objectClass": ["user"],
        "objectCategory": "person",
        "sAMAccountName": "erin",
        "memberOf": [OPS],
    }
    with pytest.raises(DirectoryMissingUniqueId):
        backend.authenticate(_spec(kind="ad", username_attribute=None), "erin", "erin-secret", OPTIONS)


def test_entry_uuid_subject_is_unchanged(directory: FakeDirectory) -> None:
    """既定（entryUUID）の subject は今までの形のまま（既存のユーザー行と一致させる）。"""
    identity = backend.authenticate(_spec(), "alice", "alice-secret", OPTIONS)
    assert identity.subject == "uuid:6f1c-alice"
    explicit = backend.authenticate(_spec(unique_id_attribute="entryuuid"), "alice", "alice-secret", OPTIONS)
    assert explicit.subject == identity.subject


def test_configured_unique_id_attribute(directory: FakeDirectory) -> None:
    """ID の属性を指定できる。文字列はそのまま、バイナリ（eDirectory の GUID など）は 16 進で使う。"""
    directory.entries[ALICE_DN]["nsUniqueId"] = "8a1b2c3d-11e1aa01-80f0c1d2-a1b2c3d4"
    directory.entries[ALICE_DN]["GUID"] = bytes([0xFF, 0x00, 0x10, 0xAB])
    by_text = backend.authenticate(_spec(unique_id_attribute="nsUniqueId"), "alice", "alice-secret", OPTIONS)
    assert by_text.subject == "id:nsuniqueid=8a1b2c3d-11e1aa01-80f0c1d2-a1b2c3d4"
    by_binary = backend.authenticate(_spec(unique_id_attribute="GUID"), "alice", "alice-secret", OPTIONS)
    assert by_binary.subject == "id:guid#ff0010ab"
    # 指定した属性がなければ、entryUUID があっても拒否する
    with pytest.raises(DirectoryMissingUniqueId):
        backend.authenticate(_spec(unique_id_attribute="ipaUniqueID"), "alice", "alice-secret", OPTIONS)


async def test_renamed_user_stays_disabled(client, directory: FakeDirectory) -> None:
    """アプリで無効にしたユーザーは、ディレクトリで DN が変わっても（改名・移動）ログインできない。"""
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    realm = f"dir:{directory_id}"
    assert (await _dir_login(realm, "alice", "alice-secret"))[0].status_code == 200
    async with session_scope() as db:
        user = await db.scalar(select(User).where(User.realm_key == realm))
        assert user is not None
        user.is_active = False

    directory.entries[f"uid=alice,ou=staff,{BASE}"] = directory.entries.pop(ALICE_DN)
    assert (await _dir_login(realm, "alice", "alice-secret"))[0].status_code == 401
    async with session_scope() as db:
        assert len((await db.scalars(select(User).where(User.realm_key == realm))).all()) == 1


async def test_connection_test_reports_a_missing_unique_id(client, directory: FakeDirectory) -> None:
    directory_id = (await client.post("/api/auth/directories", json=_directory_body())).json()["id"]
    url = f"/api/auth/directories/{directory_id}/test"
    found = (await client.post(url, json={"username": "alice"})).json()
    assert "6f1c-alice" in found["stages"][1]["message"]

    del directory.entries[ALICE_DN]["entryUUID"]
    missing = (await client.post(url, json={"username": "alice", "password": "alice-secret"})).json()
    assert missing["ok"] is False
    assert [s["stage"] for s in missing["stages"]] == ["connect", "user_search", "unique_id"]
    assert "entryUUID" in missing["stages"][-1]["message"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"kind": "ad", "group_mode": "member_of", "unique_id_attribute": "nsUniqueId"}, "objectGUID"),
        ({"unique_id_attribute": "bad attr"}, "属性名"),
        ({"unique_id_attribute": "1.2..3"}, "属性名"),
    ],
)
async def test_unique_id_attribute_validation(client, overrides: dict[str, Any], message: str) -> None:
    resp = await client.post("/api/auth/directories", json=_directory_body(**overrides))
    assert resp.status_code == 422, resp.text
    assert message in resp.json()["detail"]


async def test_unique_id_attribute_cannot_change_once_users_exist(client, directory: FakeDirectory) -> None:
    """ID の属性を変えると全員の subject が変わり、無効化をすり抜けられるので、ユーザーがいれば変えさせない。"""
    created = await client.post("/api/auth/directories", json=_directory_body(unique_id_attribute="1.3.6.1.4.1.1466.115"))
    assert created.status_code == 201, created.text
    directory_id = created.json()["id"]
    assert created.json()["unique_id_attribute"] == "1.3.6.1.4.1.1466.115"
    url = f"/api/auth/directories/{directory_id}"
    # ユーザーがいなければ変えられる。空文字は未設定（entryUUID）
    resp = await client.patch(url, json={"unique_id_attribute": ""})
    assert resp.status_code == 200 and resp.json()["unique_id_attribute"] is None

    assert (await _dir_login(f"dir:{directory_id}", "alice", "alice-secret"))[0].status_code == 200
    resp = await client.patch(url, json={"unique_id_attribute": "nsUniqueId"})
    assert resp.status_code == 422
    assert "ID" in resp.json()["detail"]
    # 断った変更は保存しない
    assert (await client.get("/api/auth/directories")).json()[0]["unique_id_attribute"] is None
    # 未設定と entryUUID の明示は同じ属性なので、変更に当たらない
    assert (await client.patch(url, json={"unique_id_attribute": "entryUUID"})).status_code == 200
    assert (await client.patch(url, json={"unique_id_attribute": None})).status_code == 200

    # 案内のとおり、無効にして削除すれば、別の ID 属性で作り直せる
    assert "作り直" in resp.json()["detail"]
    assert (await client.patch(url, json={"is_enabled": False})).status_code == 200
    assert (await client.delete(url)).status_code == 204
    directory.entries[ALICE_DN]["nsUniqueId"] = "alice-ns"
    recreated = await client.post("/api/auth/directories", json=_directory_body(unique_id_attribute="nsUniqueId"))
    assert recreated.status_code == 201, recreated.text
    resp, me = await _dir_login(f"dir:{recreated.json()['id']}", "alice", "alice-secret")
    assert resp.status_code == 200 and me is not None


def test_custom_unique_ids_keep_exact_bytes(directory: FakeDirectory) -> None:
    """前後の空白だけが違う値（Octet String など完全一致の構文）を同じユーザーにしない。"""
    directory.entries[ALICE_DN]["serialNumber"] = b"abc"
    directory.entries[BOB_DN]["serialNumber"] = b" abc"
    directory.entries[BOB_DN]["memberOf"] = [OPS]
    spec = _spec(unique_id_attribute="serialNumber")
    alice = backend.authenticate(spec, "alice", "alice-secret", OPTIONS)
    bob = backend.authenticate(spec, "bob", "bob-secret", OPTIONS)
    assert alice.subject == "id:serialnumber=abc"
    assert bob.subject != alice.subject


@pytest.mark.parametrize(
    ("attribute", "values"),
    [
        ("nsUniqueId", ["id-1", "id-2"]),
        ("entryUUID", ["6f1c-alice", "6f1c-other"]),
    ],
)
def test_multi_valued_unique_id_is_refused(directory: FakeDirectory, attribute: str, values: list[str]) -> None:
    """値の順序は保証されないので、複数の値を持つ ID 属性からはどれも選ばずに拒否する。"""
    directory.entries[ALICE_DN][attribute] = values
    with pytest.raises(DirectoryMissingUniqueId, match="複数"):
        backend.authenticate(_spec(unique_id_attribute=attribute), "alice", "alice-secret", OPTIONS)


def test_multi_valued_object_guid_is_refused(directory: FakeDirectory) -> None:
    directory.entries[f"cn=Erin,ou=people,{BASE}"] = {
        "userPassword": "erin-secret",
        "objectClass": ["user"],
        "objectCategory": "person",
        "sAMAccountName": "erin",
        "objectGUID": [uuid.uuid4().bytes_le, uuid.uuid4().bytes_le],
        "memberOf": [OPS],
    }
    with pytest.raises(DirectoryMissingUniqueId):
        backend.authenticate(_spec(kind="ad", username_attribute=None), "erin", "erin-secret", OPTIONS)


# --- 締め出し対策（Issue #254・Issue #258）---------------------------------------

VERIFICATION_HEADER = "x-vea-error-code"


class _DirectoryAdmin:
    """ディレクトリのユーザー（既定は alice）としてログインしたクライアント。"""

    def __init__(self, realm: str, username: str = "alice", password: str = "alice-secret") -> None:
        self.realm = realm
        self.credentials = {"username": username, "password": password, "realm": realm}
        self.client = _raw_client()

    async def __aenter__(self) -> AsyncClient:
        _rate_limiter._hits.clear()
        await self.client.__aenter__()
        resp = await self.client.post("/api/auth/login", json=self.credentials, headers=XHR)
        assert resp.status_code == 200, resp.text
        self.client.headers.update(XHR)
        return self.client

    async def __aexit__(self, *exc: Any) -> None:
        await self.client.__aexit__(*exc)


async def _create_directory(client) -> str:
    resp = await client.post("/api/auth/directories", json=_directory_body())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _stored_directory(directory_id: str) -> dict[str, Any]:
    from vcenter_event_assistant.db.models import DirectoryConfig

    async with session_scope() as db:
        config = await db.get(DirectoryConfig, uuid.UUID(directory_id))
        assert config is not None
        return {
            "username_attribute": config.username_attribute,
            "user_search_filter": config.user_search_filter,
            "updated_at": config.updated_at,
        }


async def test_unsaved_settings_can_be_tested(client, directory: FakeDirectory) -> None:
    """未保存の設定で接続を試せる。DB には何も書かない。"""
    body = {**_directory_body(), "username": "alice", "password": "alice-secret"}
    resp = await client.post("/api/auth/directories/test", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert [s["stage"] for s in resp.json()["stages"]] == ["connect", "user_search", "user_bind", "groups"]
    assert (await client.get("/api/auth/directories")).json() == []

    resp = await client.post("/api/auth/directories/test", json={**body, "server_uris": ["ldap://ldap.example.com"]})
    assert resp.status_code == 422


async def test_unsaved_changes_can_be_tested_on_an_existing_directory(client, directory: FakeDirectory) -> None:
    """保存済みの設定に編集中の変更を重ねて試す。保存せず、ログイン中のセッションも失効させない。"""
    directory_id = await _create_directory(client)
    before = await _stored_directory(directory_id)
    url = f"/api/auth/directories/{directory_id}/test"
    async with _DirectoryAdmin(f"dir:{directory_id}") as alice:
        # bind パスワードを送らなければ保存済みのものを使う
        resp = await client.post(url, json={**ALICE_CREDENTIALS, "changes": {"sort_order": 1}})
        assert resp.json()["ok"] is True, resp.text

        resp = await client.post(url, json={**ALICE_CREDENTIALS, "changes": {"username_attribute": "cn"}})
        assert resp.json()["ok"] is False
        assert resp.json()["stages"][-1]["stage"] == "user_search"

        resp = await client.post(url, json={**ALICE_CREDENTIALS, "mappings": [{"group_dn": OPS, "role": "admin"}]})
        assert resp.json()["ok"] is False
        assert resp.json()["stages"][-1]["stage"] == "groups"

        resp = await client.post(url, json={"changes": {"bind_password": "wrong"}})
        assert resp.json()["ok"] is False and resp.json()["stages"][0]["stage"] == "connect"

        resp = await client.post(url, json={"changes": {"server_uris": ["ldap://ldap.example.com"]}})
        assert resp.status_code == 422

        assert (await alice.get("/api/auth/me")).status_code == 200
    assert await _stored_directory(directory_id) == before


async def test_directory_admin_must_verify_changes_to_their_own_directory(client, directory: FakeDirectory) -> None:
    """(a) 自分のセッションが失効する変更は、新しい設定で admin としてログインできると確かめてから保存する。"""
    directory_id = await _create_directory(client)
    url = f"/api/auth/directories/{directory_id}"
    change = {"user_search_filter": "(uid={username})"}
    async with _DirectoryAdmin(f"dir:{directory_id}") as alice:
        resp = await alice.patch(url, json=change)
        assert resp.status_code == 409, resp.text
        assert resp.headers[VERIFICATION_HEADER] == "directory_verification_required"

        # 新しい設定ではユーザーが見つからない
        resp = await alice.patch(url, json={"username_attribute": "cn", "verification": ALICE_CREDENTIALS})
        assert resp.status_code == 409
        assert resp.headers[VERIFICATION_HEADER] == "directory_verification_failed"
        # パスワードの誤り
        resp = await alice.patch(url, json={**change, "verification": {"username": "alice", "password": "wrong"}})
        assert resp.status_code == 409
        assert resp.headers[VERIFICATION_HEADER] == "directory_verification_failed"
        # 新しい対応表では admin にならない
        resp = await alice.patch(
            url,
            json={"mappings": [{"group_dn": ADMINS, "role": "operator"}], "verification": ALICE_CREDENTIALS},
        )
        assert resp.status_code == 409
        assert resp.headers[VERIFICATION_HEADER] == "directory_verification_failed"
        stored = await _stored_directory(directory_id)
        assert stored["username_attribute"] == "uid" and stored["user_search_filter"] is None

        # 名前や表示順だけなら確かめずに保存でき、セッションも残る
        resp = await alice.patch(url, json={"name": "Renamed", "sort_order": 2})
        assert resp.status_code == 200, resp.text
        assert (await alice.get("/api/auth/me")).status_code == 200

        resp = await alice.patch(url, json={**change, "verification": ALICE_CREDENTIALS})
        assert resp.status_code == 200, resp.text
        assert resp.json()["user_search_filter"] == "(uid={username})"
        # 自分のセッションも失効する（新しい設定でログインし直す）
        assert (await alice.get("/api/auth/me")).status_code == 401
    resp, me = await _dir_login(f"dir:{directory_id}", "alice", "alice-secret")
    assert resp.status_code == 200 and me is not None and me.json()["role"] == "admin"


async def test_changes_must_be_verified_when_no_other_admin_path_exists(
    client, directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) 設定上ほかに admin の経路がなければ、ほかの経路の admin が操作するときも確かめる。"""
    directory_id = await _create_directory(client)
    url = f"/api/auth/directories/{directory_id}"
    change = {"user_search_filter": "(uid={username})"}
    # ローカルの admin がログインできる間は、確かめずに保存できる
    assert (await client.patch(url, json={"username_attribute": "cn"})).status_code == 200
    assert (await client.patch(url, json={"username_attribute": "uid"})).status_code == 200

    monkeypatch.setenv("VEA_LOCAL_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    resp = await client.patch(url, json=change)
    assert resp.status_code == 409
    assert resp.headers[VERIFICATION_HEADER] == "directory_verification_required"
    resp = await client.patch(url, json={"username_attribute": "cn", "verification": ALICE_CREDENTIALS})
    assert resp.status_code == 409
    resp = await client.patch(url, json={**change, "verification": ALICE_CREDENTIALS})
    assert resp.status_code == 200, resp.text


async def test_verification_refuses_users_disabled_in_the_app(
    client, directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #258: アプリで無効にしたユーザーの資格情報では、確かめたことにしない（保存後にログインできない）。"""
    directory_id = await _create_directory(client)
    realm = f"dir:{directory_id}"
    directory.entries[BOB_DN]["memberOf"] = [ADMINS]
    assert (await _dir_login(realm, "bob", "bob-secret"))[0].status_code == 200
    users = (await client.get("/api/auth/users")).json()
    bob_id = next(u["id"] for u in users if u["username"] == "bob")
    assert (await client.patch(f"/api/auth/users/{bob_id}", json={"is_active": False})).status_code == 200

    monkeypatch.setenv("VEA_LOCAL_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    url = f"/api/auth/directories/{directory_id}"
    change = {"user_search_filter": "(uid={username})"}
    resp = await client.patch(url, json={**change, "verification": {"username": "bob", "password": "bob-secret"}})
    assert resp.status_code == 409
    assert resp.headers[VERIFICATION_HEADER] == "directory_verification_failed"
    assert "無効" in resp.json()["detail"]
    # まだ行のない（初回ログイン前の）ユーザーなら、ログインすると有効な行が作られるので通す
    resp = await client.patch(url, json={**change, "verification": ALICE_CREDENTIALS})
    assert resp.status_code == 200, resp.text


async def test_directory_admin_cannot_disable_their_own_directory(client, directory: FakeDirectory) -> None:
    """(a) 自分のディレクトリは無効にできない。別の経路でログインして操作する。"""
    directory_id = await _create_directory(client)
    url = f"/api/auth/directories/{directory_id}"
    async with _DirectoryAdmin(f"dir:{directory_id}") as alice:
        resp = await alice.patch(url, json={"is_enabled": False, "verification": ALICE_CREDENTIALS})
        assert resp.status_code == 409
        assert "別の" in resp.json()["detail"]
        assert (await alice.get("/api/auth/me")).status_code == 200
    assert (await client.patch(url, json={"is_enabled": False})).status_code == 200


async def test_save_is_refused_if_the_directory_changed_during_verification(
    client, directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """確かめている間に設定が変わったら、確かめていない設定を保存しない。"""
    from vcenter_event_assistant.api.routes import auth_directories
    from vcenter_event_assistant.auth.timeutil import utcnow
    from vcenter_event_assistant.db.models import DirectoryConfig

    directory_id = await _create_directory(client)
    original = auth_directories.run_directory_call

    async def change_while_verifying(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        async with session_scope() as db:
            config = await db.get(DirectoryConfig, uuid.UUID(directory_id))
            assert config is not None
            config.username_attribute = "cn"
            config.updated_at = utcnow()
        return result

    monkeypatch.setattr(auth_directories, "run_directory_call", change_while_verifying)
    async with _DirectoryAdmin(f"dir:{directory_id}") as alice:
        resp = await alice.patch(
            f"/api/auth/directories/{directory_id}",
            json={"user_search_filter": "(uid={username})", "verification": ALICE_CREDENTIALS},
        )
        assert resp.status_code == 409, resp.text
        assert "ほかの操作" in resp.json()["detail"]
    assert (await _stored_directory(directory_id))["user_search_filter"] is None


async def test_mappings_endpoint_is_removed(client, directory: FakeDirectory) -> None:
    """対応表は設定と同じ PATCH で保存する（別々に送ると、1 回目で唯一の admin が締め出される）。"""
    directory_id = await _create_directory(client)
    resp = await client.put(
        f"/api/auth/directories/{directory_id}/mappings", json={"mappings": [{"group_dn": OPS, "role": "admin"}]}
    )
    assert resp.status_code in (404, 405)


async def test_verification_is_required_if_the_other_admin_path_disappears_before_saving(
    client, directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """確かめずに済むと判断した後、ロックを取るまでにほかの admin の経路がなくなったら、確かめを求める。"""
    from contextlib import asynccontextmanager

    from vcenter_event_assistant.api.routes import auth_directories
    from vcenter_event_assistant.db.models import DirectoryConfig

    directory_id = await _create_directory(client)
    other = await client.post("/api/auth/directories", json=_directory_body(name="Other LDAP"))
    other_id = other.json()["id"]
    monkeypatch.setenv("VEA_LOCAL_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    original = auth_directories.admin_change_guard

    @asynccontextmanager
    async def disable_other_first(db: Any):
        async with session_scope() as other_db:
            config = await other_db.get(DirectoryConfig, uuid.UUID(other_id))
            assert config is not None
            config.is_enabled = False
        async with original(db):
            yield

    monkeypatch.setattr(auth_directories, "admin_change_guard", disable_other_first)
    resp = await client.patch(f"/api/auth/directories/{directory_id}", json={"user_search_filter": "(uid={username})"})
    assert resp.status_code == 409, resp.text
    assert resp.headers[VERIFICATION_HEADER] == "directory_verification_required"
    assert (await _stored_directory(directory_id))["user_search_filter"] is None


async def test_service_account_password_changes_must_be_verified(client, directory: FakeDirectory) -> None:
    """bind パスワードはセッションを失効させないが、誤るとこの後のログインがすべて失敗するので確かめる。"""
    directory_id = await _create_directory(client)
    url = f"/api/auth/directories/{directory_id}"
    async with _DirectoryAdmin(f"dir:{directory_id}") as alice:
        resp = await alice.patch(url, json={"bind_password": "wrong"})
        assert resp.status_code == 409
        assert resp.headers[VERIFICATION_HEADER] == "directory_verification_required"
        resp = await alice.patch(url, json={"bind_password": "wrong", "verification": ALICE_CREDENTIALS})
        assert resp.status_code == 409
        assert resp.headers[VERIFICATION_HEADER] == "directory_verification_failed"
        resp = await alice.patch(url, json={"timeout_seconds": 3})
        assert resp.headers.get(VERIFICATION_HEADER) == "directory_verification_required"

        # 確かめられれば保存でき、ログイン中のセッションは残す（認証・ロールの根拠は変わらない）
        resp = await alice.patch(url, json={"bind_password": "svc-secret", "verification": ALICE_CREDENTIALS})
        assert resp.status_code == 200, resp.text
        assert (await alice.get("/api/auth/me")).status_code == 200
    resp, _ = await _dir_login(f"dir:{directory_id}", "alice", "alice-secret")
    assert resp.status_code == 200
