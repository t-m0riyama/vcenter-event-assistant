"""JSON encoding for the collector plugin worker protocol.

外部プラグインは別プロセスで実行するため、``CollectionContext`` と ``CollectionBatch`` を
プロセス境界を越えられる形に変換する必要がある。変換規則をここ 1 箇所に集約する。

``open_vcenter_connection`` は関数であり転送できない。代わりに接続パラメータ
(``ConnectionParams``) を別メッセージとして送り、ワーカー側（＝本アプリのコード）が
接続を張ってプラグインへファクトリとして渡す。これによりプラグイン側の契約
(``packages/plugin-api``) は変更せずに済む。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectorManifest,
    EventInput,
    MetricDefinition,
    MetricSampleInput,
    VCenterTarget,
)

PROTOCOL_VERSION = 1


@dataclass(frozen=True, slots=True)
class ConnectionParams:
    """vCenter 接続に必要な値一式（パスワードを含む）。

    ワーカーへは collect 要求ごとに送る。ログや API レスポンスへ出してはならない。
    """

    host: str
    protocol: str
    port: int
    username: str
    password: str
    verify_ssl: bool
    proxy_url: str | None = None
    ca_bundle_path: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "protocol": self.protocol,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "verify_ssl": self.verify_ssl,
            "proxy_url": self.proxy_url,
            "ca_bundle_path": self.ca_bundle_path,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "ConnectionParams":
        return cls(
            host=str(raw["host"]),
            protocol=str(raw["protocol"]),
            port=int(raw["port"]),
            username=str(raw["username"]),
            password=str(raw["password"]),
            verify_ssl=bool(raw["verify_ssl"]),
            proxy_url=raw.get("proxy_url"),
            ca_bundle_path=raw.get("ca_bundle_path"),
        )

    def __repr__(self) -> str:  # pragma: no cover - 事故防止の表示のみ
        return f"ConnectionParams(host={self.host!r}, username={self.username!r}, password=***)"


def _dt_to_json(value: datetime) -> str:
    return value.isoformat()


def _dt_from_json(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        # tz 無しは契約違反。ここで黙って UTC を補うと検証をすり抜けるため拒否する。
        raise ValueError("datetime must be timezone-aware")
    return parsed


def metric_definition_to_json(definition: MetricDefinition) -> dict[str, Any]:
    return {
        "key": definition.key,
        "display_name": definition.display_name,
        "unit": definition.unit,
        "entity_type": definition.entity_type,
        "series_mode": definition.series_mode,
        "category": definition.category,
        "description": definition.description,
    }


def metric_definition_from_json(raw: dict[str, Any]) -> MetricDefinition:
    return MetricDefinition(
        key=str(raw["key"]),
        display_name=str(raw["display_name"]),
        unit=str(raw["unit"]),
        entity_type=str(raw["entity_type"]),
        series_mode=raw.get("series_mode", "entity"),
        category=str(raw.get("category", "other")),
        description=str(raw.get("description", "")),
    )


def manifest_to_json(manifest: CollectorManifest) -> dict[str, Any]:
    return {
        "id": manifest.id,
        "display_name": manifest.display_name,
        "version": manifest.version,
        "api_version": manifest.api_version,
        "data_kinds": sorted(manifest.data_kinds),
        "default_interval_seconds": manifest.default_interval_seconds,
        "metric_definitions": [
            metric_definition_to_json(d) for d in manifest.metric_definitions
        ],
    }


def manifest_from_json(raw: dict[str, Any]) -> CollectorManifest:
    return CollectorManifest(
        id=str(raw["id"]),
        display_name=str(raw["display_name"]),
        version=str(raw["version"]),
        api_version=int(raw["api_version"]),
        data_kinds=frozenset(raw.get("data_kinds", ())),
        default_interval_seconds=int(raw.get("default_interval_seconds", 300)),
        metric_definitions=tuple(
            metric_definition_from_json(d) for d in raw.get("metric_definitions", ())
        ),
    )


def target_to_json(target: VCenterTarget) -> dict[str, Any]:
    return {
        "id": str(target.id),
        "name": target.name,
        "host": target.host,
        "protocol": target.protocol,
        "port": target.port,
        "username": target.username,
        "verify_ssl": target.verify_ssl,
    }


def target_from_json(raw: dict[str, Any]) -> VCenterTarget:
    return VCenterTarget(
        id=uuid.UUID(str(raw["id"])),
        name=str(raw["name"]),
        host=str(raw["host"]),
        protocol=str(raw["protocol"]),
        port=int(raw["port"]),
        username=str(raw["username"]),
        verify_ssl=bool(raw["verify_ssl"]),
    )


def context_to_json(context) -> dict[str, Any]:
    """``open_vcenter_connection`` を除いた転送可能な部分だけを返す。"""
    return {
        "target": target_to_json(context.target),
        "config": dict(context.config),
        "previous_cursor": context.previous_cursor,
        "mock_mode": context.mock_mode,
    }


def batch_to_json(batch: CollectionBatch) -> dict[str, Any]:
    return {
        "events": [
            {
                "occurred_at": _dt_to_json(event.occurred_at),
                "event_type": event.event_type,
                "message": event.message,
                "vmware_key": event.vmware_key,
                "severity": event.severity,
                "user_name": event.user_name,
                "entity_name": event.entity_name,
                "entity_type": event.entity_type,
                "chain_id": event.chain_id,
            }
            for event in batch.events
        ],
        "metrics": [
            {
                "sampled_at": _dt_to_json(sample.sampled_at),
                "entity_type": sample.entity_type,
                "entity_moid": sample.entity_moid,
                "entity_name": sample.entity_name,
                "metric_key": sample.metric_key,
                "value": sample.value,
            }
            for sample in batch.metrics
        ],
        "next_cursor": batch.next_cursor,
    }


def batch_from_json(raw: dict[str, Any]) -> CollectionBatch:
    return CollectionBatch(
        events=tuple(
            EventInput(
                occurred_at=_dt_from_json(str(event["occurred_at"])),
                event_type=str(event["event_type"]),
                message=str(event["message"]),
                vmware_key=int(event["vmware_key"]),
                severity=event.get("severity"),
                user_name=event.get("user_name"),
                entity_name=event.get("entity_name"),
                entity_type=event.get("entity_type"),
                chain_id=event.get("chain_id"),
            )
            for event in raw.get("events", ())
        ),
        metrics=tuple(
            MetricSampleInput(
                sampled_at=_dt_from_json(str(sample["sampled_at"])),
                entity_type=str(sample["entity_type"]),
                entity_moid=str(sample["entity_moid"]),
                entity_name=str(sample["entity_name"]),
                metric_key=str(sample["metric_key"]),
                value=float(sample["value"]),
            )
            for sample in raw.get("metrics", ())
        ),
        next_cursor=raw.get("next_cursor"),
    )
