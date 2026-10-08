"""認証ディレクトリ（AD / LDAP）の管理 API のスキーマ。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from vcenter_event_assistant.auth.roles import Role

DirectoryKind = Literal["ad", "ldap"]
TransportSecurity = Literal["ldaps", "starttls", "none"]
GroupMode = Literal["ad_nested", "member_of", "group_search"]
GroupMemberValue = Literal["dn", "username"]


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


class DirectoryUpdate(BaseModel):
    """省略した項目は変えない。``bind_password`` を省略すると今の値を保つ（消すには ``clear_bind_password``）。"""

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
    ad_upn_suffix: str | None = Field(default=None, max_length=256)
    display_name_attribute: str | None = Field(default=None, max_length=128)
    email_attribute: str | None = Field(default=None, max_length=128)
    group_mode: GroupMode | None = None
    group_search_base: str | None = Field(default=None, max_length=1024)
    group_search_filter: str | None = Field(default=None, max_length=1024)
    group_member_attribute: str | None = Field(default=None, max_length=128)
    group_member_value: GroupMemberValue | None = None


class DirectoryRead(_DirectoryFields):
    id: uuid.UUID
    has_bind_password: bool
    mappings: list[GroupRoleMappingRead]
    user_count: int
    created_at: datetime
    updated_at: datetime


class DirectoryMappingsUpdate(BaseModel):
    mappings: list[GroupRoleMappingIn] = Field(max_length=200)


class DirectoryTestRequest(BaseModel):
    username: str | None = Field(default=None, max_length=256)
    password: str | None = Field(default=None, max_length=1024)


class DirectoryTestStage(BaseModel):
    stage: Literal["connect", "user_search", "user_bind", "groups"]
    ok: bool
    message: str


class DirectoryTestResponse(BaseModel):
    ok: bool
    stages: list[DirectoryTestStage]
