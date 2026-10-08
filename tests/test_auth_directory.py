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
from vcenter_event_assistant.settings import get_settings

XHR = {"X-Requested-With": "XMLHttpRequest"}
BASE = "dc=example,dc=com"
SVC_DN = f"cn=svc,{BASE}"
ALICE_DN = f"uid=alice,ou=people,{BASE}"
BOB_DN = f"uid=bob,ou=people,{BASE}"
ADMINS = f"cn=Admins,ou=groups,{BASE}"
OPS = f"cn=Ops,ou=groups,{BASE}"


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


def test_ad_finds_users_by_sam_or_upn(directory: FakeDirectory) -> None:
    carol = f"cn=Carol,ou=people,{BASE}"
    directory.entries[carol] = {
        "userPassword": "carol-secret",
        "objectClass": ["user"],
        "objectCategory": "person",
        "sAMAccountName": "carol",
        "userPrincipalName": "carol@example.com",
        "msDS-PrincipalName": "CORP\\carol",
        "memberOf": [OPS],
    }
    spec = _spec(kind="ad", ad_upn_suffix="example.com", username_attribute=None)
    by_sam = backend.authenticate(spec, "CORP\\carol", "carol-secret", OPTIONS)
    by_upn = backend.authenticate(spec, "carol@example.com", "carol-secret", OPTIONS)
    assert by_sam.username == by_upn.username == "carol"
    # objectGUID がなければ DN で識別する（どちらの入力でも同じユーザー行になる）
    assert by_sam.subject == by_upn.subject == f"dn:{normalize_dn(carol)}"
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

    mappings = await client.put(
        f"/api/auth/directories/{directory_id}/mappings",
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


def test_long_subjects_are_hashed_not_truncated() -> None:
    from vcenter_event_assistant.auth.service import _subject_key

    prefix = "dn:" + "ou=x," * 120
    a, b = prefix + "cn=alice", prefix + "cn=bob"
    assert len(a) > 512
    assert _subject_key(a) != _subject_key(b)
    assert len(_subject_key(a)) <= 512 and _subject_key(a).startswith("sha256:")
    assert _subject_key("uuid:short") == "uuid:short"


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
    url = f"/api/auth/directories/{directory_id}/mappings"
    without_admin = {"mappings": [{"group_dn": OPS, "role": "operator"}]}

    # ローカルの admin がログインできる間は、admin の対応をなくしてもよい
    assert (await client.put(url, json=without_admin)).status_code == 200
    assert (await client.put(url, json={"mappings": [{"group_dn": ADMINS, "role": "admin"}]})).status_code == 200

    # ディレクトリ専用の運用では、唯一の admin の対応はなくせない
    monkeypatch.setenv("VEA_LOCAL_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    resp = await client.put(url, json=without_admin)
    assert resp.status_code == 409 and "管理者" in resp.json()["detail"]
    # ほかに admin の対応を持つ有効なディレクトリがあればよい
    other = _directory_body(name="Other LDAP")
    assert (await client.post("/api/auth/directories", json=other)).status_code == 201
    assert (await client.put(url, json=without_admin)).status_code == 200


def test_ad_domain_qualified_login_matches_the_domain(directory: FakeDirectory) -> None:
    """DOMAIN\\user では、別ドメインの同名アカウントを選ばない（あいまいにもしない）。"""
    for domain, ou in (("CORP", "corp"), ("LAB", "lab")):
        directory.entries[f"cn=Dave,ou={ou},{BASE}"] = {
            "userPassword": f"{ou}-secret",
            "objectClass": ["user"],
            "objectCategory": "person",
            "sAMAccountName": "dave",
            "msDS-PrincipalName": f"{domain}\\dave",
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
        resp = await client.put(
            f"/api/auth/directories/{directory_id}/mappings",
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
        resp = await client.put(
            f"/api/auth/directories/{directory_id}/mappings",
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
    resp = await client.put(
        f"/api/auth/directories/{directory_id}/mappings",
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
    conn = _TruncatingConnection(backend.AD_QUALIFIED_CANDIDATES_LIMIT)
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
