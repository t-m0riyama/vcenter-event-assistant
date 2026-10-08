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
    f = backend.ad_user_filter("CORP\\alice", "example.com")
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
        ({"bind_password": None}, "パスワード"),
        ({"user_search_filter": "(uid=fixed)"}, "{username}"),
        ({"group_mode": "group_search"}, "検索ベース"),
        ({"ca_cert_pem": "not a certificate"}, "PEM"),
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
