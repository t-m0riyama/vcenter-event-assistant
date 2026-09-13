"""Sample collector plugin for vCenter Event Assistant.

ESXi ホストごとに合成の温度メトリクスを 1 点だけ返す最小のコレクタである。
プラグインを書くときの雛形と、ホットリロード／プロセス分離の動作確認を兼ねる。

``MetricCollector`` を継承すると、実装するのは :meth:`TemperatureCollector.sample` だけに
なる。以下はすべて基底が引き受ける。

- クラス属性からの ``CollectorManifest`` の生成（``data_kinds`` の導出を含む）
- vCenter 接続の open / close
- ContainerView の走査と ``Destroy()``（``vmware`` ヘルパ経由）
- ブロッキング処理のスレッド退避（キャンセルされてもセッションを取り残さない）
- ``MOCK_MODE=true`` のときの合成データ
- ``CollectionBatch`` の組み立て

依存は ``vcenter-event-assistant-plugin-api`` だけであり、アプリ本体は import しない。
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Iterable, Iterator
from typing import Any

from vcenter_event_assistant_plugin_api import (
    CollectionContext,
    MetricCollector,
    MetricDefinition,
    MetricSampleInput,
    config,
    get_plugin_logger,
    vmware,
)

PLUGIN_ID = "example.host.temperature"

#: メトリクスの宣言。``at()`` がここから ``metric_key`` / ``entity_type`` /
#: timezone-aware なタイムスタンプを補うので、キーを二度書く必要はない。
TEMPERATURE = MetricDefinition(
    key="example.host.temperature_c",
    display_name="Host temperature",
    unit="C",
    entity_type="HostSystem",
    series_mode="entity",
    category="hardware",
    description="Synthetic host temperature emitted by the sample plugin.",
)

#: 障害注入モード。プロセス分離の確認用であり、通常運用では設定しない。
#: ``hang`` = 応答しない / ``crash`` = ワーカーを即死させる / ``raise`` = 例外送出。
FAULT_ENV_VAR = "EXAMPLE_COLLECTOR_FAULT"

logger = get_plugin_logger(PLUGIN_ID)


def _read_temperature(entity_moid: str, sensor: str) -> float:
    """本来はここでセンサーを読む。サンプルなので決定的な擬似値を返す。"""
    rng = random.Random(f"{entity_moid}:{sensor}")
    return round(30.0 + rng.random() * 20.0, 1)


def _inject_fault_if_requested() -> None:
    fault = os.environ.get(FAULT_ENV_VAR, "").strip().lower()
    if fault == "hang":
        # timeout_seconds を超えると、アプリ側がワーカーごと kill する。
        time.sleep(3600)
    elif fault == "crash":
        # ワーカープロセスの異常終了。アプリ本体は生き続ける。
        os._exit(9)
    elif fault == "raise":
        # 例外の詳細はアプリの外へ出ない（型名のみが failed として記録される）。
        raise RuntimeError("synthetic failure with a secret-looking value")


class TemperatureCollector(MetricCollector):
    """ESXi ホストの温度を模した合成メトリクスを返すサンプルコレクタ。"""

    id = PLUGIN_ID
    display_name = "Example Host Temperature"
    version = "0.1.0"
    metrics = (TEMPERATURE,)
    default_interval_seconds = 300

    def sample(
        self, si: Any, context: CollectionContext
    ) -> Iterator[MetricSampleInput]:
        """接続済みの vCenter から 1 回分のサンプルを返す。**同期でよい。**

        基底がスレッドへ逃がし、戻り値をスレッド内で確定させる。
        """
        _inject_fault_if_requested()

        # 設定値は TOML / 環境変数 / 管理画面から与えられる。経路によって型が違うので
        # （環境変数由来は常に str）、必ず config ヘルパ経由で読む。
        # 機密はプラグインが所有する環境変数から読むこと。
        sensor = config.get_str(context.config, "sensor", "system-board")
        assert sensor is not None

        # `vmware.iter_hosts` が ContainerView の生成と `Destroy()` を引き受け、
        # 切断中のホストも除く（切断中は統計を返さないか、属性アクセスで失敗する）。
        # 型は文字列で指定されるので、プラグインは pyVmomi を import しなくてよい。
        hosts = vmware.iter_hosts(si)
        logger.info("sampling %d host(s) sensor=%s", len(hosts), sensor)
        for host in hosts:
            entity_moid = vmware.moid(host)
            yield TEMPERATURE.at(
                entity_moid=entity_moid,
                entity_name=host.name,
                value=_read_temperature(entity_moid, sensor),
            )

    def sample_mock(
        self, context: CollectionContext
    ) -> Iterable[MetricSampleInput]:
        """``MOCK_MODE=true`` のときの合成データ。

        宣言した ``metrics`` から決定的な値を作る既定の実装で足りるので、ここでは
        障害注入だけを挟んで基底に委ねる。合成データを自前で用意する必要はない。
        """
        _inject_fault_if_requested()
        return super().sample_mock(context)


#: entry point から呼ばれる引数なしファクトリ。クラス自体がそのまま使える。
build_collector = TemperatureCollector
