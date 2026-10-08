"""認証 API のスキーマ。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from vcenter_event_assistant.auth.roles import Role


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(max_length=1024)
    realm: str = Field(default="local", max_length=64)


class RealmRead(BaseModel):
    id: str
    name: str
    kind: str


class RealmsResponse(BaseModel):
    auth_enabled: bool
    realms: list[RealmRead]


class MeResponse(BaseModel):
    auth_enabled: bool
    username: str
    display_name: str | None = None
    role: str
    realm: str
    can_change_password: bool
    # サーバがセッションの最終利用時刻を更新する間隔（秒）。クライアントは API を呼ばない操作も
    # この間隔で報告する（無操作期限が切れる前に伝えるため）。認証が無効なら None
    session_activity_interval_seconds: int | None = None
    # 利用者の ID。API 応答の X-VEA-Principal と照合し、別アカウントへの切り替わりを検知する。認証が無効なら None
    principal_id: str | None = None


class ChangeOwnPasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class UserRead(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str | None = None
    email: str | None = None
    role: Role
    realm: str
    is_local: bool
    is_active: bool
    locked: bool
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(max_length=1024)
    role: Role = Role.VIEWER
    display_name: str | None = Field(default=None, max_length=256)
    email: str | None = Field(default=None, max_length=320)


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=256)
    email: str | None = Field(default=None, max_length=320)


class AdminPasswordReset(BaseModel):
    password: str = Field(max_length=1024)
