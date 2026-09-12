"""Sample collector plugin for vCenter Event Assistant.

ホストごとに合成の温度メトリクスを 1 点だけ返す最小のコレクタである。
プラグインを書くときの雛形と、ホットリロード／プロセス分離の動作確認を兼ねる。

実装として押さえている点:

- 依存は ``vcenter-event-assistant-plugin-api`` だけであり、アプリ本体を import しない。
- entry point は ``vcenter_event_assistant.collectors`` グループの引数なしファクトリ。
- ``manifest.id`` と ``metric_definitions[].key`` は、インストール済みの全コレクタの
  あいだで一意である必要がある（衝突するとレジストリが ``failed`` として弾く）。
- vCenter へは ``context.open_vcenter_connection()`` 経由でのみ触れる。接続の確立と
  切断はアプリ側が行うため、プラグインは認証情報を受け取らない。
- ``context.mock_mode`` が真のときは実接続せず合成値を返す（``MOCK_MODE=true`` での確認用）。
- ブロッキング処理は ``asyncio.to_thread`` に逃がす。イベントループを止めると、
  同じワーカープロセス上の他の処理まで巻き添えになる。
"""

from __future__ import annotations

import asyncio
import os
import random
from datetime import datetime, timezone

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectionContext,
    CollectorManifest,
    MetricDefinition,
    MetricSampleInput,
)

METRIC_KEY = "example.host.temperature_c"

#: 障害注入モード。プロセス分離の確認用であり、通常運用では設定しない。
#: ``hang`` = 応答しない / ``crash`` = ワーカーを即死させる / ``raise`` = 例外送出。
FAULT_ENV_VAR = "EXAMPLE_COLLECTOR_FAULT"


def _synthetic_hosts() -> list[tuple[str, str]]:
    return [("host-1", "esxi-01"), ("host-2", "esxi-02")]


def _read_hosts_blocking(si) -> list[tuple[str, str]]:
    """接続済みセッションから HostSystem の (moid, name) を読む。

    pyVmomi の呼び出しは同期 API なので、必ずスレッドへ逃がして呼ぶこと。
    """
    content = si.RetrieveContent()
    view = content.viewManager.CreateContainerView(
        content.rootFolder, ["HostSystem"], True
    )
    try:
        return [(host._moId, host.name) for host in view.view]
    finally:
        view.Destroy()


def _read_temperature(entity_moid: str, sensor: str) -> float:
    """本来はここでセンサーを読む。サンプルなので決定的な擬似値を返す。"""
    rng = random.Random(f"{entity_moid}:{sensor}")
    return round(30.0 + rng.random() * 20.0, 1)


async def _inject_fault_if_requested() -> None:
    fault = os.environ.get(FAULT_ENV_VAR, "").strip().lower()
    if fault == "hang":
        # timeout_seconds を超えると、アプリ側がワーカーごと kill する。
        await asyncio.sleep(3600)
    elif fault == "crash":
        # ワーカープロセスの異常終了。アプリ本体は生き続ける。
        os._exit(9)
    elif fault == "raise":
        # 例外の詳細はアプリの外へ出ない（型名のみが failed として記録される）。
        raise RuntimeError("synthetic failure with a secret-looking value")


class TemperatureCollector:
    """ESXi ホストの温度を模した合成メトリクスを返すサンプルコレクタ。"""

    manifest = CollectorManifest(
        id="example.host.temperature",
        display_name="Example Host Temperature",
        version="0.1.0",
        data_kinds=frozenset({"metric"}),
        default_interval_seconds=300,
        metric_definitions=(
            MetricDefinition(
                key=METRIC_KEY,
                display_name="Host temperature",
                unit="C",
                entity_type="HostSystem",
                series_mode="entity",
                category="hardware",
                description="Synthetic host temperature emitted by the sample plugin.",
            ),
        ),
    )

    async def start(self) -> None:
        """ワーカー起動後、最初の collect の前に 1 度だけ呼ばれる。"""
        return None

    async def stop(self) -> None:
        """無効化・リロード・アンインストール時に呼ばれる。"""
        return None

    async def collect(self, context: CollectionContext) -> CollectionBatch:
        await _inject_fault_if_requested()

        # 設定値は TOML / 環境変数 / 管理画面から与えられる（機密は環境変数で受けること）。
        sensor = str(context.config.get("sensor", "system-board"))

        if context.mock_mode:
            hosts = _synthetic_hosts()
        else:
            async with context.open_vcenter_connection() as si:
                hosts = await asyncio.to_thread(_read_hosts_blocking, si)

        sampled_at = datetime.now(timezone.utc)
        metrics = tuple(
            MetricSampleInput(
                sampled_at=sampled_at,
                entity_type="HostSystem",
                entity_moid=moid,
                entity_name=name,
                metric_key=METRIC_KEY,
                value=_read_temperature(moid, sensor),
            )
            for moid, name in hosts
        )
        # メトリクスのみのコレクタはカーソルを持たないため next_cursor は返さない。
        return CollectionBatch(metrics=metrics)


def build_collector() -> TemperatureCollector:
    """entry point から呼ばれる引数なしファクトリ。"""
    return TemperatureCollector()
