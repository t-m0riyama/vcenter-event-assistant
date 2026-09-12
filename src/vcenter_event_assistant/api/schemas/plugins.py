"""Collector plugin status and management API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from vcenter_event_assistant.api.schemas.base import _normalize_to_utc


class CollectorRunStatusRead(BaseModel):
    """Latest execution status for one collector and vCenter."""

    vcenter_id: uuid.UUID
    vcenter_name: str
    status: Literal["idle", "running", "ok", "failed"]
    collector_version: str
    last_started_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    events_inserted: int
    metrics_inserted: int
    error: str | None

    @field_validator(
        "last_started_at", "last_success_at", "last_failure_at", mode="before"
    )
    @classmethod
    def datetimes_to_utc(cls, value: object) -> datetime | None:
        if value is None:
            return None
        return _normalize_to_utc(value)


class CollectorStatusRead(BaseModel):
    """Installed, configured, or failed collector registration."""

    id: str
    display_name: str | None
    source: str
    status: Literal["enabled", "disabled", "failed"]
    error: str | None
    version: str | None
    api_version: int | None
    data_kinds: list[Literal["event", "metric"]]
    interval_seconds: int | None
    timeout_seconds: float | None
    # 環境変数で固定され、DB 設定より優先されるため UI で編集させない共通フィールド。
    env_locked_fields: list[str] = []
    runs: list[CollectorRunStatusRead]


class CollectorStatusListResponse(BaseModel):
    generation: int
    management_enabled: bool = False
    # DB に保存済みだが、まだリロードされておらず稼働中の世代に反映されていない変更がある。
    reload_required: bool = False
    collectors: list[CollectorStatusRead]


class CollectorSettingUpdate(BaseModel):
    """PATCH による部分更新。``None`` のフィールドは変更しない。"""

    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=10, le=86400)
    timeout_seconds: float | None = Field(default=None, gt=0, le=86400)


class InstalledPluginRead(BaseModel):
    """1 つのインストール済み（または進行中・失敗）配布物。"""

    distribution: str
    version: str
    source: Literal["upload", "index", ""]
    origin: str
    status: Literal["installing", "installed", "failed"]
    error: str | None
    installed_at: datetime

    @field_validator("installed_at", mode="before")
    @classmethod
    def installed_at_to_utc(cls, value: object) -> datetime | None:
        return _normalize_to_utc(value)


class InstalledPluginListResponse(BaseModel):
    management_enabled: bool
    index_install_enabled: bool
    plugins: list[InstalledPluginRead]


class PluginInstallRequest(BaseModel):
    """インデックスからの名前指定インストール（アップロードは multipart で受ける）。"""

    requirement: str = Field(min_length=1, max_length=128)


class CollectorReloadResponse(BaseModel):
    generation: int
    jobs_added: list[str]
    jobs_removed: list[str]
    jobs_rescheduled: list[str]
    collectors: list[CollectorStatusRead]
