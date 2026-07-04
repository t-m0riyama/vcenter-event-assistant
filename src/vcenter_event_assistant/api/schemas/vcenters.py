"""vCenter CRUD API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vcenter_event_assistant.db.encrypted_string import ENC_PREFIX


def _reject_storage_prefix_password(value: str) -> str:
    if value.startswith(ENC_PREFIX):
        raise ValueError(
            f"password must not start with {ENC_PREFIX!r} (reserved for encrypted storage format)"
        )
    return value


class VCenterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    host: str = Field(min_length=1, max_length=512)
    protocol: Literal["https", "http"] = "https"
    port: int = Field(default=443, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=2048)
    verify_ssl: bool = False
    is_enabled: bool = True

    @field_validator("password")
    @classmethod
    def password_not_storage_prefix(cls, value: str) -> str:
        return _reject_storage_prefix_password(value)


class VCenterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    host: str | None = Field(default=None, min_length=1, max_length=512)
    protocol: Literal["https", "http"] | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=512)
    password: str | None = Field(default=None, min_length=1, max_length=2048)
    verify_ssl: bool | None = None
    is_enabled: bool | None = None

    @field_validator("password")
    @classmethod
    def password_not_storage_prefix(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _reject_storage_prefix_password(value)


class VCenterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    host: str
    protocol: Literal["https", "http"]
    port: int
    username: str
    verify_ssl: bool
    is_enabled: bool
    created_at: datetime
