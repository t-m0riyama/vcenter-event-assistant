"""認証ディレクトリ（AD / LDAP）の管理 API のスキーマ。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.db.encrypted_string import ENC_PREFIX

DirectoryKind = Literal["ad", "ldap"]
TransportSecurity = Literal["ldaps", "starttls", "none"]
GroupMode = Literal["ad_nested", "member_of", "group_search"]
GroupMemberValue = Literal["dn", "username"]



# bind パスワードの UTF-8 でのバイト数の上限。暗号化（Fernet + base64）すると 4/3 倍強に増えるので、
# 1024 バイトなら暗号化後も約 1470 文字で、保存先の列（EncryptedString(2048)）に収まる
BIND_PASSWORD_MAX_BYTES = 1024


def _check_bind_password_value(value: str | None) -> str | None:
    if value is None:
        return value
    # ``enc:`` で始まる値は暗号化済みとみなされて暗号化されず、読み出し時の復号に失敗するため受け付けない
    if value.startswith(ENC_PREFIX):
        raise ValueError(f"bind password must not start with {ENC_PREFIX!r} (reserved for encrypted storage format)")
    # 文字数ではなくバイト数で制限する（マルチバイト文字は暗号化後に列の長さを超え得る）
    if len(value.encode("utf-8")) > BIND_PASSWORD_MAX_BYTES:
        raise ValueError(f"bind password must be at most {BIND_PASSWORD_MAX_BYTES} bytes in UTF-8")
    return value


class GroupRoleMappingIn(BaseModel):
    group_dn: str = Field(min_length=1, max_length=1024)
    role: Role


class GroupRoleMappingRead(BaseModel):
    group_dn: str
    role: Role


class _DirectoryFields(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: DirectoryKind
    is_enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=10_000)
    server_uris: list[str] = Field(min_length=1, max_length=10)
    transport_security: TransportSecurity = "ldaps"
    tls_verify: bool = True
    ca_cert_pem: str | None = Field(default=None, max_length=65536)
    bind_dn: str | None = Field(default=None, max_length=1024)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    user_search_base: str = Field(min_length=1, max_length=1024)
    user_search_filter: str | None = Field(default=None, max_length=1024)
    username_attribute: str | None = Field(default=None, max_length=128)
    unique_id_attribute: str | None = Field(default=None, max_length=128)
    ad_upn_suffix: str | None = Field(default=None, max_length=256)
    display_name_attribute: str | None = Field(default=None, max_length=128)
    email_attribute: str | None = Field(default=None, max_length=128)
    group_mode: GroupMode = "member_of"
    group_search_base: str | None = Field(default=None, max_length=1024)
    group_search_filter: str | None = Field(default=None, max_length=1024)
    group_member_attribute: str | None = Field(default=None, max_length=128)
    group_member_value: GroupMemberValue | None = None


class DirectoryCreate(_DirectoryFields):
    # 書き込み専用。応答には返さない（has_bind_password だけを返す）
    bind_password: str | None = Field(default=None, max_length=1024)
    mappings: list[GroupRoleMappingIn] = Field(default_factory=list, max_length=200)

    _check_bind_password = field_validator("bind_password")(_check_bind_password_value)


class DirectoryCredentials(BaseModel):
    """保存の前の確認に使う、ディレクトリのユーザーの資格情報（保存しない・ログに出さない）。"""

    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


class DirectoryChanges(BaseModel):
    """設定の変更。省略した項目は変えない。``bind_password`` を省略すると今の値を保つ（消すには ``clear_bind_password``）。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    server_uris: list[str] | None = Field(default=None, min_length=1, max_length=10)
    transport_security: TransportSecurity | None = None
    tls_verify: bool | None = None
    ca_cert_pem: str | None = Field(default=None, max_length=65536)
    bind_dn: str | None = Field(default=None, max_length=1024)
    bind_password: str | None = Field(default=None, max_length=1024)
    clear_bind_password: bool = False
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    user_search_base: str | None = Field(default=None, min_length=1, max_length=1024)
    user_search_filter: str | None = Field(default=None, max_length=1024)
    username_attribute: str | None = Field(default=None, max_length=128)
    unique_id_attribute: str | None = Field(default=None, max_length=128)
    ad_upn_suffix: str | None = Field(default=None, max_length=256)
    display_name_attribute: str | None = Field(default=None, max_length=128)
    email_attribute: str | None = Field(default=None, max_length=128)
    group_mode: GroupMode | None = None
    group_search_base: str | None = Field(default=None, max_length=1024)
    group_search_filter: str | None = Field(default=None, max_length=1024)
    group_member_attribute: str | None = Field(default=None, max_length=128)
    group_member_value: GroupMemberValue | None = None

    _check_bind_password = field_validator("bind_password")(_check_bind_password_value)


class DirectoryUpdate(DirectoryChanges):
    """設定と対応表をまとめて保存する（セッションの失効も 1 回にする）。

    ``mappings`` を省略すると対応表は変えない（空のリストは「すべて外す」）。``verification`` は、保存で
    admin としてログインする手段を失うおそれがあるときに、新しい設定で admin としてログインできることを
    確かめるための資格情報。
    """

    mappings: list[GroupRoleMappingIn] | None = Field(default=None, max_length=200)
    verification: DirectoryCredentials | None = None


class DirectoryRead(_DirectoryFields):
    id: uuid.UUID
    has_bind_password: bool
    mappings: list[GroupRoleMappingRead]
    user_count: int
    created_at: datetime
    updated_at: datetime


class DirectoryPolicy(BaseModel):
    """今の設定で許される接続の方針。画面が操作できない項目とその理由を出すために使う。"""

    # 証明書を検証しない設定（tls_verify=false）を保存できるか（VEA_DIRECTORY_ALLOW_INSECURE_TLS）
    allow_insecure_tls: bool
    # 暗号化しない接続（transport_security=none）を保存できるか（本番では不可）
    allow_no_transport_security: bool


class DirectoryTestRequest(BaseModel):
    """保存済みの設定で試す。``changes`` / ``mappings`` を渡すと、保存せずに重ねて試す。"""

    username: str | None = Field(default=None, max_length=256)
    password: str | None = Field(default=None, max_length=1024)
    changes: DirectoryChanges | None = None
    mappings: list[GroupRoleMappingIn] | None = Field(default=None, max_length=200)


class DirectoryTestUnsavedRequest(DirectoryCreate):
    """まだ保存していない設定で試す（新規作成の画面から）。"""

    username: str | None = Field(default=None, max_length=256)
    password: str | None = Field(default=None, max_length=1024)


class DirectoryTestStage(BaseModel):
    stage: Literal["connect", "user_search", "unique_id", "user_bind", "groups"]
    ok: bool
    message: str


class DirectoryTestResponse(BaseModel):
    ok: bool
    stages: list[DirectoryTestStage]
