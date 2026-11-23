"""モックモード用のイベント／メトリクス収集（pyVmomi 不使用）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from vcenter_event_assistant_plugin_api import EventEntityInput

MOCK_HOST_MOID = "host-mock-01"
MOCK_VM_MOID = "vm-mock-01"

_MOCK_EVENT_TYPES = (
    "vim.event.MockDemoVmPoweredOnEvent",
    "vim.event.MockDemoAlarmStatusChangedEvent",
    "vim.event.MockDemoHostConnectionLostEvent",
)


def fetch_mock_events_blocking(
    *,
    since: datetime | None = None,
) -> tuple[list[dict[str, Any]], datetime | None]:
    """取り込み経路向けの合成イベントを返す。

    ``vmware_key`` は通常の合成イベントでは秒単位の時刻、ホスト切断では 30 分枠と枠内の連番から導出する。
    同じキーの再取り込みは ON CONFLICT で吸収される。
    ``since`` は実収集とのシグネチャ互換のため受け取る。
    直近の合成イベント 2 件と、30 分ごとのホスト切断 3 件を返す。
    """
    _ = since
    now = datetime.now(timezone.utc)

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
            "entity_moid": MOCK_HOST_MOID,
            "entities": (EventEntityInput(
                "host", entity_moid=MOCK_HOST_MOID, entity_name="esxi-mock-01",
                entity_type="HostSystem", is_primary=True,
            ),),
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
            "entity_moid": MOCK_VM_MOID,
            "entities": (EventEntityInput(
                "vm", entity_moid=MOCK_VM_MOID, entity_name="vm-mock-web-01",
                entity_type="VirtualMachine", is_primary=True,
            ),),
            "vmware_key": key_base + 1,
            "chain_id": key_base + 1,
        },
    ]
    # 同じ 30 分枠の切断は、収集を繰り返しても同じキーと時刻にする。
    interval = key_base // (30 * 60)
    interval_start = datetime.fromtimestamp(interval * 30 * 60, tz=timezone.utc)
    for i, minutes in enumerate((8, 4, 1)):
        rows.append({
            "occurred_at": interval_start - timedelta(minutes=minutes),
            "event_type": "vim.event.HostConnectionLostEvent",
            "message": "（モック）ホストと vCenter の接続が切れました。",
            "entity_name": "esxi-mock-01",
            "entity_type": "HostSystem",
            "entity_moid": MOCK_HOST_MOID,
            "entities": (EventEntityInput(
                "host", entity_moid=MOCK_HOST_MOID, entity_name="esxi-mock-01",
                entity_type="HostSystem", is_primary=True,
            ),),
            "vmware_key": -(interval * 3 + i + 1),
        })
    rows.sort(key=lambda row: row["occurred_at"])
    return rows, now


def fetch_mock_tasks_blocking(since: datetime | None) -> list[dict[str, Any]]:
    """同じ 30 分枠では、同じキーと完了時刻でタスクを返す。

    ``since`` は実収集との互換のために受け取り、重複は取り込み時に除く。
    """
    _ = since
    now = datetime.now(timezone.utc)
    interval = int(now.timestamp()) // (30 * 60)
    interval_start = datetime.fromtimestamp(interval * 30 * 60, tz=timezone.utc)
    entity = EventEntityInput(
        "entity",
        entity_moid=MOCK_VM_MOID,
        entity_name="vm-mock-web-01",
        entity_type="VirtualMachine",
        is_primary=True,
    )
    examples = (
        ("success", "VirtualMachine.powerOn", "info", "succeeded"),
        (
            "error",
            "VirtualMachine.powerOn",
            "error",
            "failed: Invalid power state [InvalidPowerState]",
        ),
        ("canceled", "VirtualMachine.migrate", "warning", "was canceled"),
    )
    rows = []
    for i, (result, operation, severity, outcome) in enumerate(examples):
        completed = interval_start - timedelta(minutes=3 - i)
        started = completed - timedelta(seconds=12.3)
        rows.append(
            {
                "occurred_at": completed,
                "event_type": f"task.{result}.{operation}",
                "message": (
                    f"Task {operation} {outcome} "
                    f"(started: {started.isoformat()}, duration: 12.3s, reason: user)"
                ),
                "severity": severity,
                "user_name": "mock-user",
                "entity_name": entity.entity_name,
                "entity_type": entity.entity_type,
                "entity_moid": entity.entity_moid,
                "entities": (entity,),
                "vmware_key": -(interval * 3 + i + 1),
            }
        )
    return rows


def sample_mock_hosts_blocking() -> list[dict[str, Any]]:
    """ホスト／Datastore の合成メトリクス行を返す。"""
    now = datetime.now(timezone.utc)
    # 分単位でわずかに変動させてグラフに動きを出す
    wobble = (int(now.timestamp()) // 60) % 20
    ds_moid = "datastore-mock-01"
    return [
        {
            "sampled_at": now,
            "entity_type": "HostSystem",
            "entity_moid": MOCK_HOST_MOID,
            "entity_name": "esxi-mock-01",
            "metric_key": "host.cpu.usage_pct",
            "value": float(35 + wobble),
        },
        {
            "sampled_at": now,
            "entity_type": "HostSystem",
            "entity_moid": MOCK_HOST_MOID,
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
