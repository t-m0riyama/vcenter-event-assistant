"""Public, dependency-free contracts and helpers for collector plugins.

**2 つのバージョンがあり、意味が違う。**

- :data:`PLUGIN_API_VERSION` は*契約世代*である。アプリは ``manifest.api_version`` が
  これと一致しないプラグインを ``failed`` として拒否する。したがってヘルパを追加しても
  **上げてはならない**。上げた瞬間に既存の全プラグインが動かなくなる。
- パッケージの :data:`__version__` は通常の SemVer である。後方互換な追加で minor を
  上げる。プラグインは ``vcenter-event-assistant-plugin-api>=1.1,<2`` のように宣言する。

``import vcenter_event_assistant_plugin_api`` は第三者パッケージを一切読み込まない。
pyVmomi を使うヘルパは :mod:`~vcenter_event_assistant_plugin_api.vmware` に分離され、
そこでも関数内で遅延 import する。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

#: 配布パッケージのバージョン（SemVer）。機能検出に使える。
__version__ = "1.1.0"

#: 契約世代。アプリが ``manifest.api_version`` と突き合わせる。**安易に上げないこと。**
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

    def at(
        self,
        *,
        entity_moid: str,
        entity_name: str,
        value: float,
        sampled_at: datetime | None = None,
        entity_type: str | None = None,
    ) -> MetricSampleInput:
        """この定義に沿った :class:`MetricSampleInput` を組み立てる。

        ``metric_key`` と ``entity_type`` を定義から補い、``sampled_at`` を省略すると
        timezone-aware な現在時刻を入れる。これにより、宣言とサンプルでメトリクスキーを
        二重に書く必要がなくなり、naive な datetime も混入しなくなる。

        長すぎる ``entity_name`` などは**黙って切り詰めない**。値を勝手に変えないためで、
        超過は :func:`validation.check_batch` が warning として報告する。切り詰めたい
        場合は :func:`limits.truncate` を明示的に呼ぶこと。
        """
        from vcenter_event_assistant_plugin_api.timeutils import now_utc

        return MetricSampleInput(
            sampled_at=sampled_at if sampled_at is not None else now_utc(),
            entity_type=entity_type if entity_type is not None else self.entity_type,
            entity_moid=entity_moid,
            entity_name=entity_name,
            metric_key=self.key,
            value=float(value),
        )


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


# 契約の定義が揃ったあとにサブモジュールを読む。サブモジュール側はこのパッケージから
# データクラスを import するため、この順序でないと循環する。
# pyVmomi を必要とする `vmware` と、pytest を触りうる `testing` はここでは読まない。
from vcenter_event_assistant_plugin_api import limits as limits  # noqa: E402
from vcenter_event_assistant_plugin_api import logs as logs  # noqa: E402
from vcenter_event_assistant_plugin_api import timeutils as timeutils  # noqa: E402
from vcenter_event_assistant_plugin_api import validation as validation  # noqa: E402
from vcenter_event_assistant_plugin_api.blocking import (  # noqa: E402
    run_blocking as run_blocking,
)
from vcenter_event_assistant_plugin_api.logs import (  # noqa: E402
    PLUGIN_LOGGER_NAMESPACE as PLUGIN_LOGGER_NAMESPACE,
)
from vcenter_event_assistant_plugin_api.logs import (  # noqa: E402
    get_plugin_logger as get_plugin_logger,
)
from vcenter_event_assistant_plugin_api.timeutils import (  # noqa: E402
    ensure_aware as ensure_aware,
)
from vcenter_event_assistant_plugin_api.timeutils import now_utc as now_utc  # noqa: E402
from vcenter_event_assistant_plugin_api.timeutils import to_utc as to_utc  # noqa: E402
from vcenter_event_assistant_plugin_api.validation import (  # noqa: E402
    BatchValidationError as BatchValidationError,
)
from vcenter_event_assistant_plugin_api.validation import Issue as Issue  # noqa: E402
from vcenter_event_assistant_plugin_api.validation import (  # noqa: E402
    ManifestValidationError as ManifestValidationError,
)
from vcenter_event_assistant_plugin_api.validation import (  # noqa: E402
    check_batch as check_batch,
)
from vcenter_event_assistant_plugin_api.validation import (  # noqa: E402
    check_manifest as check_manifest,
)
from vcenter_event_assistant_plugin_api.validation import (  # noqa: E402
    validate_batch as validate_batch,
)
from vcenter_event_assistant_plugin_api.validation import (  # noqa: E402
    validate_manifest as validate_manifest,
)

__all__ = [
    "PLUGIN_API_VERSION",
    "PLUGIN_LOGGER_NAMESPACE",
    "BatchValidationError",
    "CollectionBatch",
    "CollectionContext",
    "CollectorManifest",
    "CollectorPlugin",
    "ConnectionFactory",
    "DataKind",
    "EventInput",
    "Issue",
    "ManifestValidationError",
    "MetricDefinition",
    "MetricSampleInput",
    "SeriesMode",
    "VCenterTarget",
    "__version__",
    "check_batch",
    "check_manifest",
    "ensure_aware",
    "get_plugin_logger",
    "limits",
    "logs",
    "now_utc",
    "run_blocking",
    "timeutils",
    "to_utc",
    "validate_batch",
    "validate_manifest",
    "validation",
]
