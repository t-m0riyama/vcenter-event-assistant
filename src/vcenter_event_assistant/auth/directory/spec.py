"""ディレクトリ設定を、別スレッドで使える不変の値にしたもの。

ldap3 の呼び出しは同期なので ``anyio.to_thread`` で実行する。ORM オブジェクト（遅延読み込みや
セッションに束縛された属性）をスレッドに渡さないよう、必要な値だけをここに写す。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from vcenter_event_assistant.auth.directory.role_mapping import normalize_dn
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.db.models import DirectoryConfig


DEFAULT_UNIQUE_ID_ATTRIBUTE = "entryUUID"


@dataclass(frozen=True)
class DirectorySpec:
    id: uuid.UUID
    name: str
    kind: str  # ad | ldap
    server_uris: tuple[str, ...]
    transport_security: str  # ldaps | starttls | none
    tls_verify: bool
    ca_cert_pem: str | None
    bind_dn: str | None
    bind_password: str | None
    timeout_seconds: int
    user_search_base: str
    user_search_filter: str | None
    username_attribute: str | None
    ad_upn_suffix: str | None
    display_name_attribute: str | None
    email_attribute: str | None
    group_mode: str  # ad_nested | member_of | group_search
    group_search_base: str | None
    group_search_filter: str | None
    group_member_attribute: str | None
    group_member_value: str | None
    # (正規化した DN, ロール)
    mappings: tuple[tuple[str, Role], ...]
    # 表示用（接続試験の結果に出す、登録したままの DN）
    mapping_labels: tuple[tuple[str, Role], ...] = ()
    # LDAP のみ。ユーザーの ID に使う属性（未設定なら entryUUID）
    unique_id_attribute: str | None = None

    @property
    def id_attribute(self) -> str:
        """ユーザーの ID に使う属性。AD は objectGUID に決まっている。"""
        if self.kind == "ad":
            return "objectGUID"
        return self.unique_id_attribute or DEFAULT_UNIQUE_ID_ATTRIBUTE

    @property
    def realm_key(self) -> str:
        return realm_key_for(self.id)


def realm_key_for(directory_id: uuid.UUID) -> str:
    """``users.realm_key`` とログイン画面の realm の値。"""
    return f"dir:{directory_id}"


def spec_from_model(config: DirectoryConfig) -> DirectorySpec:
    return DirectorySpec(
        id=config.id,
        name=config.name,
        kind=config.kind,
        server_uris=tuple(config.server_uris or ()),
        transport_security=config.transport_security,
        tls_verify=config.tls_verify,
        ca_cert_pem=config.ca_cert_pem or None,
        bind_dn=config.bind_dn or None,
        bind_password=config.bind_password or None,
        timeout_seconds=config.timeout_seconds,
        user_search_base=config.user_search_base,
        user_search_filter=config.user_search_filter or None,
        username_attribute=config.username_attribute or None,
        ad_upn_suffix=config.ad_upn_suffix or None,
        display_name_attribute=config.display_name_attribute or None,
        email_attribute=config.email_attribute or None,
        group_mode=config.group_mode,
        group_search_base=config.group_search_base or None,
        group_search_filter=config.group_search_filter or None,
        group_member_attribute=config.group_member_attribute or None,
        group_member_value=config.group_member_value or None,
        mappings=tuple(
            (m.group_dn_normalized or normalize_dn(m.group_dn), Role(m.role)) for m in config.mappings
        ),
        mapping_labels=tuple((m.group_dn, Role(m.role)) for m in config.mappings),
        unique_id_attribute=config.unique_id_attribute or None,
    )
