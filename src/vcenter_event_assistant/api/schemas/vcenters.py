"""vCenter CRUD API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VCenterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    host: str = Field(min_length=1, max_length=512)
    protocol: Literal["https", "http"] = "https"
    port: int = Field(default=443, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=2048)
    is_enabled: bool = True


class VCenterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    host: str | None = Field(default=None, min_length=1, max_length=512)
    protocol: Literal["https", "http"] | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=512)
    password: str | None = Field(default=None, min_length=1, max_length=2048)
    is_enabled: bool | None = None


class VCenterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    host: str
    protocol: Literal["https", "http"]
    port: int
    username: str
    is_enabled: bool
    created_at: datetime
