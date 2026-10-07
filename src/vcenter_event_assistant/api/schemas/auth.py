"""認証 API のスキーマ。"""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class ChangeOwnPasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)
