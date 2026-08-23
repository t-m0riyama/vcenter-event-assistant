"""モックモード用のイベント／メトリクス収集（pyVmomi 不使用）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_MOCK_EVENT_TYPES = (
    "vim.event.VmPoweredOnEvent",
    "vim.event.AlarmStatusChangedEvent",
    "vim.event.HostConnectionLostEvent",
)


def fetch_mock_events_blocking(
    *,
    since: datetime | None = None,
) -> tuple[list[dict[str, Any]], datetime | None]:
    """取り込み経路向けの合成イベントを返す。

    ``since`` 以降（または直近）に 1〜2 件を生成する。``vmware_key`` は秒単位の時刻から
    導出し、再実行で重複しやすい境界は ON CONFLICT で吸収される。
    """
    now = datetime.now(timezone.utc)
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if since is not None and now <= since:
        # カーソル直後の再取得では空でもよいが、デモでは最低 1 件を返す
        pass

    key_base = int(now.timestamp())
    rows: list[dict[str, Any]] = [
        {
            "occurred_at": now,
            "event_type": _MOCK_EVENT_TYPES[key_base % len(_MOCK_EVENT_TYPES)],
            "message": "（モック）合成イベント — デモ用データです。",
            "severity": "info" if key_base % 3 else "error",
            "user_name": "mock-user",
            "entity_name": "esxi-mock-01",
            "entity_type": "HostSystem",
            "vmware_key": key_base,
            "chain_id": key_base,
        },
        {
            "occurred_at": now,
            "event_type": _MOCK_EVENT_TYPES[(key_base + 1) % len(_MOCK_EVENT_TYPES)],
            "message": "（モック）2件目の合成イベント。",
            "severity": "warning",
            "user_name": None,
            "entity_name": "vm-mock-web-01",
            "entity_type": "VirtualMachine",
            "vmware_key": key_base + 1,
            "chain_id": key_base + 1,
        },
    ]
    return rows, now


def sample_mock_hosts_blocking() -> list[dict[str, Any]]:
    """ホスト／Datastore の合成メトリクス行を返す。"""
    now = datetime.now(timezone.utc)
    # 分単位でわずかに変動させてグラフに動きを出す
    wobble = (int(now.timestamp()) // 60) % 20
    host_moid = "host-mock-01"
    ds_moid = "datastore-mock-01"
    return [
        {
            "sampled_at": now,
            "entity_type": "HostSystem",
            "entity_moid": host_moid,
            "entity_name": "esxi-mock-01",
            "metric_key": "host.cpu.usage_pct",
            "value": float(35 + wobble),
        },
        {
            "sampled_at": now,
            "entity_type": "HostSystem",
            "entity_moid": host_moid,
            "entity_name": "esxi-mock-01",
            "metric_key": "host.mem.usage_pct",
            "value": float(48 + wobble // 2),
        },
        {
            "sampled_at": now,
            "entity_type": "Datastore",
            "entity_moid": ds_moid,
            "entity_name": "mock-datastore",
            "metric_key": "datastore.space.used_pct",
            "value": float(62 + wobble // 4),
        },
        {
            "sampled_at": now,
            "entity_type": "Datastore",
            "entity_moid": ds_moid,
            "entity_name": "mock-datastore",
            "metric_key": "datastore.space.used_bytes",
            "value": float(1_500_000_000_000 + wobble * 10_000_000),
        },
    ]
