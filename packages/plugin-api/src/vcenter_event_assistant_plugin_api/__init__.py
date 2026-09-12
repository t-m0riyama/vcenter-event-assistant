"""Public, dependency-free contracts for collector plugins."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

PLUGIN_API_VERSION = 1
DataKind = Literal["event", "metric"]
SeriesMode = Literal["entity", "single"]


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    key: str
    display_name: str
    unit: str
    entity_type: str
    series_mode: SeriesMode = "entity"
    category: str = "other"
    description: str = ""


@dataclass(frozen=True, slots=True)
class CollectorManifest:
    id: str
    display_name: str
    version: str
    api_version: int = PLUGIN_API_VERSION
    data_kinds: frozenset[DataKind] = field(default_factory=frozenset)
    default_interval_seconds: int = 300
    metric_definitions: tuple[MetricDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class EventInput:
    occurred_at: datetime
    event_type: str
    message: str
    vmware_key: int
    severity: str | None = None
    user_name: str | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    chain_id: int | None = None


@dataclass(frozen=True, slots=True)
class MetricSampleInput:
    sampled_at: datetime
    entity_type: str
    entity_moid: str
    entity_name: str
    metric_key: str
    value: float


@dataclass(frozen=True, slots=True)
class CollectionBatch:
    events: tuple[EventInput, ...] = ()
    metrics: tuple[MetricSampleInput, ...] = ()
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class VCenterTarget:
    id: UUID
    name: str
    host: str
    protocol: str
    port: int
    username: str
    verify_ssl: bool


ConnectionFactory = Callable[[], AbstractAsyncContextManager[Any]]


@dataclass(frozen=True, slots=True)
class CollectionContext:
    target: VCenterTarget
    config: Mapping[str, Any]
    previous_cursor: str | None
    open_vcenter_connection: ConnectionFactory
    mock_mode: bool = False


@runtime_checkable
class CollectorPlugin(Protocol):
    manifest: CollectorManifest

    async def start(self) -> None: ...

    async def collect(self, context: CollectionContext) -> CollectionBatch: ...

    async def stop(self) -> None: ...


__all__ = [
    "PLUGIN_API_VERSION",
    "CollectionBatch",
    "CollectionContext",
    "CollectorManifest",
    "CollectorPlugin",
    "EventInput",
    "MetricDefinition",
    "MetricSampleInput",
    "VCenterTarget",
]
