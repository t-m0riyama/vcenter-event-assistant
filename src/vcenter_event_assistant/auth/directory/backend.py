"""ディレクトリでの認証（同期。別スレッドで呼ぶ）。

1. サービスアカウント（未設定なら匿名）で bind し、ユーザーを検索する。ちょうど 1 件のときだけ続ける
2. 見つかったユーザーの DN と入力されたパスワードで、本人として bind する
3. 所属グループを調べ、グループとロールの対応表から最も強いロールを決める（どれにも一致しなければ拒否）

フィルタに入れる値（ユーザー名・DN）はすべて ``escape_filter_chars`` でエスケープする。
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ldap3 import BASE, SUBTREE, Connection
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from vcenter_event_assistant.auth.directory import connection
from vcenter_event_assistant.auth.directory.connection import BindRejected, ConnectOptions
from vcenter_event_assistant.auth.directory.errors import (
    DirectoryAuthFailed,
    DirectoryConfigError,
    DirectoryMissingUniqueId,
    DirectoryNoRole,
    DirectoryUnavailable,
)
from vcenter_event_assistant.auth.directory.role_mapping import normalize_dn, resolve_role
from vcenter_event_assistant.auth.directory.spec import DEFAULT_UNIQUE_ID_ATTRIBUTE, DirectorySpec
from vcenter_event_assistant.auth.roles import Role

# AD の LDAP_MATCHING_RULE_IN_CHAIN（入れ子のグループもたどって所属を判定する）
AD_IN_CHAIN_RULE = "1.2.840.113556.1.4.1941"
# AD の userAccountControl の ACCOUNTDISABLE ビットを除外する（LDAP_MATCHING_RULE_BIT_AND）
AD_ENABLED_ACCOUNT_FILTER = "(!(userAccountControl:1.2.840.113556.1.4.803:=2))"
USERNAME_MAX_LENGTH = 256


@dataclass(frozen=True)
class DirectoryIdentity:
    """ディレクトリで認証できたユーザー。"""

    subject: str
    username: str
    display_name: str | None
    email: str | None
    dn: str
    role: Role
    # 対応表と一致した（正規化済みの）グループ DN
    matched_groups: tuple[str, ...] = ()


@dataclass
class _Entry:
    dn: str
    attributes: dict[str, list[Any]] = field(default_factory=dict)
    raw: dict[str, list[bytes]] = field(default_factory=dict)

    def first(self, name: str | None) -> str | None:
        if not name:
            return None
        for key, values in self.attributes.items():
            if key.casefold() == name.casefold():
                items = values if isinstance(values, list) else [values]
                for v in items:
                    text = v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
                    if text.strip():
                        return text.strip()
        return None

    def all(self, name: str) -> list[str]:
        for key, values in self.attributes.items():
            if key.casefold() == name.casefold():
                items = values if isinstance(values, list) else [values]
                return [v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v) for v in items]
        return []

    def raw_all(self, name: str) -> list[bytes]:
        for key, values in self.raw.items():
            if key.casefold() == name.casefold():
                return list(values)
        return []


def clean_username(username: str) -> str:
    """入力されたユーザー名の正規化。空・長すぎる・制御文字を含む値は拒否する。"""
    value = unicodedata.normalize("NFKC", username).strip()
    if not value or len(value) > USERNAME_MAX_LENGTH or any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise DirectoryAuthFailed("ユーザー名が不正です。", reason="invalid_username")
    return value


def ad_user_filter(username: str, upn_suffix: str | None) -> str:
    """AD のユーザー検索フィルタ。sAMAccountName と UPN のどちらでも見つかるようにする。

    ``@`` を含む名前は UPN だけで探し、含まない名前は sAMAccountName と、``upn_suffix`` を付けた UPN で探す。
    ``DOMAIN\\user`` 形式は ``find_user`` が sAMAccountName で候補を探し、ドメインまで照合する。
    無効化されたアカウントは除く。
    """
    name = username
    if "@" in name:
        # UPN で入力されたら UPN だけで探す（同名の別ドメインの sAMAccountName に広げない）
        match = f"(userPrincipalName={escape_filter_chars(name)})"
    else:
        clauses = [f"(sAMAccountName={escape_filter_chars(name)})"]
        if upn_suffix:
            clauses.append(f"(userPrincipalName={escape_filter_chars(f'{name}@{upn_suffix}')})")
        match = clauses[0] if len(clauses) == 1 else f"(|{''.join(clauses)})"
    return f"(&(objectCategory=person)(objectClass=user){AD_ENABLED_ACCOUNT_FILTER}{match})"


def ldap_user_filter(spec: DirectorySpec, username: str) -> str:
    """汎用 LDAP のユーザー検索フィルタ。テンプレートの ``{username}`` をエスケープした値に置き換える。"""
    escaped = escape_filter_chars(username)
    template = spec.user_search_filter or f"({spec.username_attribute or 'uid'}={{username}})"
    if "{username}" not in template:
        raise DirectoryConfigError("ユーザー検索フィルタに {username} がありません。")
    return template.replace("{username}", escaped)


def ad_in_chain_filter(group_dn: str) -> str:
    """ユーザーがグループ（入れ子を含む）に属するかを、ユーザーのエントリに対して調べるフィルタ。"""
    return f"(memberOf:{AD_IN_CHAIN_RULE}:={escape_filter_chars(group_dn)})"


def _entries(conn: Connection) -> Iterator[_Entry]:
    for item in conn.response or []:
        if item.get("type") != "searchResEntry":
            continue
        yield _Entry(
            dn=item.get("dn", ""),
            attributes=dict(item.get("attributes") or {}),
            raw=dict(item.get("raw_attributes") or {}),
        )


def _search(conn: Connection, base: str, search_filter: str, *, scope: Any = SUBTREE, attributes: list[str], size_limit: int = 0) -> list[_Entry]:
    try:
        conn.search(base, search_filter, search_scope=scope, attributes=attributes, size_limit=size_limit)
    except LDAPException as exc:
        raise DirectoryUnavailable(f"検索に失敗しました（{str(exc)[:200]}）") from None
    result = conn.result or {}
    code = result.get("result", 0)
    if code == 32:  # noSuchObject
        # 検索の起点がない（検索ベースの誤り・削除など）。0 件として扱うと、設定の誤りが
        # 「ユーザーが見つからない」に見えてしまうので、設定の問題として扱う
        raise DirectoryConfigError(f"検索の起点のエントリが見つかりません（{base[:200]}）。検索ベースを確認してください。")
    if code not in (0, 4):  # success / sizeLimitExceeded
        raise DirectoryUnavailable(f"検索に失敗しました（{result.get('description')}）")
    entries = list(_entries(conn))
    # sizeLimitExceeded は、こちらが指定した件数まで取れたとき（それ以上あると分かったとき）だけ受け入れる。
    # サーバ側の上限で途中までしか返らなかった結果からは、一意かどうかもグループの所属も判断できない
    if code == 4 and (size_limit == 0 or len(entries) < size_limit):
        raise DirectoryUnavailable("サーバの件数上限で検索結果が途中までしか返りませんでした。")
    return entries


def _user_attributes(spec: DirectorySpec) -> list[str]:
    attrs = {spec.display_name_attribute or "displayName", spec.email_attribute or "mail", spec.id_attribute}
    if spec.kind == "ad":
        attrs |= {"sAMAccountName", "userPrincipalName"}
    else:
        attrs.add(spec.username_attribute or "uid")
    if spec.group_mode == "member_of":
        attrs.add("memberOf")
    return sorted(attrs)


def unique_id(spec: DirectorySpec, entry: _Entry) -> str:
    """ディレクトリ内で変わらない ID（``users.subject`` の元）。取れなければ ``DirectoryMissingUniqueId``。

    AD は objectGUID、LDAP は ID 属性（既定は entryUUID）。DN は改名・移動で変わるので使わない。
    値がちょうど 1 つのときだけ使う。属性の値の順序は保証されないので、複数あるとどれを選んでも
    検索のたびに（レプリカごとに）ID が変わり得て、無効にしたユーザーが別の行として作り直される。
    """
    attribute = spec.id_attribute
    values = entry.raw_all(attribute)
    if len(values) != 1 or not values[0]:
        reason = "複数の値があります" if len(values) > 1 else "値がありません"
        raise DirectoryMissingUniqueId(
            f"ID 属性 {attribute} の{reason}。このユーザーはログインできません"
            "（値がちょうど 1 つの、変わらない属性を指定し、サービスアカウントの読み取り権限を確認してください）。"
        )
    raw = values[0]
    if spec.kind == "ad":
        if len(raw) != 16:
            raise DirectoryMissingUniqueId(f"ID 属性 {attribute} の値が GUID（16 バイト）ではありません。")
        return f"guid:{uuid.UUID(bytes_le=raw)}"
    if attribute.casefold() == DEFAULT_UNIQUE_ID_ATTRIBUTE.casefold():
        # #253 より前の行と同じ形（前後の空白を除いて小文字にする）。entryUUID は UUID の構文なので加工しても衝突しない
        value = raw.decode("utf-8", "replace").strip()
        if not value:
            raise DirectoryMissingUniqueId(f"ID 属性 {attribute} の値が空です。")
        return f"uuid:{value.casefold()}"
    # 文字列の値はそのまま、バイナリ（eDirectory の GUID など）は 16 進にする。
    # 区切り（``=`` と ``#``）を変えて、文字列とバイナリの値が同じ subject にならないようにする。
    # 空白の除去などの加工はしない（Octet String のように完全一致で比べる構文では、前後の空白だけが
    # 違う値も別のエントリの ID になり得るので、加工すると別のユーザーが同じ行になる）
    try:
        text: str | None = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is not None and text.isprintable():
        return f"id:{attribute.casefold()}={text}"
    return f"id:{attribute.casefold()}#{raw.hex()}"


def resolved_username(spec: DirectorySpec, entry: _Entry, typed: str) -> str:
    """ディレクトリ上のユーザー名（AD は sAMAccountName、LDAP は username_attribute）。"""
    if spec.kind == "ad":
        return entry.first("sAMAccountName") or typed
    return entry.first(spec.username_attribute or "uid") or typed


# DOMAIN\user で同名の候補を調べる上限（これを超える同名アカウントは扱わない）
AD_QUALIFIED_CANDIDATES_LIMIT = 20


def _ad_sam_only_filter(sam: str) -> str:
    return (
        f"(&(objectCategory=person)(objectClass=user){AD_ENABLED_ACCOUNT_FILTER}"
        f"(sAMAccountName={escape_filter_chars(sam)}))"
    )


def _find_ad_qualified(conn: Connection, spec: DirectorySpec, domain: str, sam: str) -> list[_Entry]:
    """``DOMAIN\\user`` の入力で、ドメインまで一致するアカウントだけを返す。

    ドメイン部分を捨てて sAMAccountName だけで探すと、検索ベースが複数のドメインにまたがるとき、
    別ドメインの同名アカウントで認証してしまう。各候補の msDS-PrincipalName（``DOMAIN\\sam`` の形で
    AD が返す構築属性）を読み、入力と一致するものだけを残す。
    """
    candidates = _search(
        conn,
        spec.user_search_base,
        _ad_sam_only_filter(sam),
        attributes=_user_attributes(spec),
        # 1 件多く求め、上限ちょうどの完全な結果と、上限を超える結果を見分ける
        size_limit=AD_QUALIFIED_CANDIDATES_LIMIT + 1,
    )
    if len(candidates) > AD_QUALIFIED_CANDIDATES_LIMIT:
        # 候補が上限を超えて残りを確かめられないので、一意とは言えない
        raise DirectoryAuthFailed("同じ名前のユーザーが多すぎます。", reason="ambiguous_user")
    expected = f"{domain}\\{sam}".casefold()
    matched: list[_Entry] = []
    for entry in candidates:
        # 構築属性はエントリ自身を対象にした検索でしか返らないことがあるため、1 件ずつ読む
        principal = _search(conn, entry.dn, "(objectClass=*)", scope=BASE, attributes=["msDS-PrincipalName"])
        name = principal[0].first("msDS-PrincipalName") if principal else None
        if name and name.casefold() == expected:
            matched.append(entry)
    return matched


def find_user(conn: Connection, spec: DirectorySpec, username: str) -> _Entry:
    """ユーザーを 1 件だけ見つける。見つからない・複数なら ``DirectoryAuthFailed``。"""
    if spec.kind == "ad" and "\\" in username:
        domain, sam = username.split("\\", 1)
        if not domain or not sam or "\\" in sam:
            raise DirectoryAuthFailed("ユーザー名が不正です。", reason="invalid_username")
        found = _find_ad_qualified(conn, spec, domain, sam)
    else:
        search_filter = (
            ad_user_filter(username, spec.ad_upn_suffix) if spec.kind == "ad" else ldap_user_filter(spec, username)
        )
        found = _search(conn, spec.user_search_base, search_filter, attributes=_user_attributes(spec), size_limit=2)
    if not found:
        raise DirectoryAuthFailed("ユーザーが見つかりません。", reason="unknown_user")
    if len(found) > 1:
        raise DirectoryAuthFailed("同じ名前のユーザーが複数見つかりました。", reason="ambiguous_user")
    return found[0]


def member_groups(conn: Connection, spec: DirectorySpec, entry: _Entry, username: str) -> set[str]:
    """ユーザーが属するグループ（正規化済み DN）。AD の入れ子判定では対応表のグループだけを調べる。"""
    if spec.group_mode == "member_of":
        return {normalize_dn(dn) for dn in entry.all("memberOf")}
    if spec.group_mode == "ad_nested":
        groups: set[str] = set()
        for label, _role in spec.mapping_labels:
            if _search(conn, entry.dn, ad_in_chain_filter(label), scope=BASE, attributes=["1.1"]):
                groups.add(normalize_dn(label))
        return groups
    if spec.group_mode == "group_search":
        if not spec.group_search_base:
            raise DirectoryConfigError("グループの検索ベースが設定されていません。")
        attribute = spec.group_member_attribute or "member"
        value = username if spec.group_member_value == "username" else entry.dn
        member = f"({attribute}={escape_filter_chars(value)})"
        base_filter = spec.group_search_filter or "(objectClass=*)"
        found = _search(conn, spec.group_search_base, f"(&{base_filter}{member})", attributes=["1.1"])
        return {normalize_dn(e.dn) for e in found}
    raise DirectoryConfigError(f"未対応のグループ判定方式です: {spec.group_mode}")


def service_connection(spec: DirectorySpec, options: ConnectOptions) -> Connection:
    """ユーザー検索に使う接続（サービスアカウント、未設定なら匿名）。"""
    if spec.bind_dn and not spec.bind_password:
        raise DirectoryConfigError("サービスアカウントのパスワードが設定されていません。")
    try:
        return connection.connect(spec, user=spec.bind_dn, password=spec.bind_password, options=options)
    except BindRejected:
        raise DirectoryUnavailable("サービスアカウントで bind できません（DN またはパスワードを確認してください）。") from None


def verify_user_password(spec: DirectorySpec, dn: str, password: str, options: ConnectOptions) -> None:
    try:
        conn = connection.connect(spec, user=dn, password=password, options=options)
    except BindRejected:
        raise DirectoryAuthFailed("パスワードが正しくありません。", reason="bad_password") from None
    conn.unbind()


def authenticate(
    spec: DirectorySpec,
    username: str,
    password: str,
    options: ConnectOptions,
) -> DirectoryIdentity:
    """ディレクトリで認証し、ロールを決める。失敗したら ``DirectoryError`` の派生を投げる。"""
    if not password:
        raise DirectoryAuthFailed("パスワードが空です。", reason="empty_password")
    name = clean_username(username)
    conn = service_connection(spec, options)
    try:
        entry = find_user(conn, spec, name)
        verify_user_password(spec, entry.dn, password, options)
        # ロールより先に確かめる（ID が取れないのは設定の問題なので、どのユーザーでも運用者に知らせる）
        subject = unique_id(spec, entry)
        groups = member_groups(conn, spec, entry, resolved_username(spec, entry, name))
    finally:
        conn.unbind()
    role = resolve_role(groups, spec.mappings)
    matched = tuple(sorted(g for g, _r in spec.mappings if g in groups))
    if role is None:
        raise DirectoryNoRole("どのグループの対応にも当てはまりません。")
    return DirectoryIdentity(
        subject=subject,
        username=resolved_username(spec, entry, name),
        display_name=entry.first(spec.display_name_attribute or "displayName"),
        email=entry.first(spec.email_attribute or "mail"),
        dn=entry.dn,
        role=role,
        matched_groups=matched,
    )
