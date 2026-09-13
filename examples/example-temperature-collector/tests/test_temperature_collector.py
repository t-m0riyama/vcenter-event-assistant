"""サンプルコレクタの単体テスト。

アプリを起動せず、vCenter も用意せずに ``pytest`` だけで通る。これが
``plugin_api.testing`` を使う狙いである。
"""

from __future__ import annotations

import pytest
from vcenter_event_assistant_plugin_api.testing import (
    FakeServiceInstance,
    assert_manifest_valid,
    fake_host,
    failing_connection,
    run_collect,
)

from example_temperature_collector import PLUGIN_ID, TemperatureCollector


def test_the_manifest_matches_the_entry_point_name() -> None:
    """entry point 名と ``manifest.id`` は一致していなければならない。

    ずれるとレジストリが ``configured plugin is not installed`` のような
    遠い文言で失敗する。
    """
    manifest = TemperatureCollector.manifest
    assert manifest.id == PLUGIN_ID
    assert_manifest_valid(manifest)


async def test_it_samples_only_connected_hosts() -> None:
    si = FakeServiceInstance(
        hosts=[
            fake_host("host-1", "esxi-a"),
            fake_host("host-2", "esxi-b", connected=False),
        ]
    )
    batch = await run_collect(TemperatureCollector(), connection=si)

    assert [sample.entity_moid for sample in batch.metrics] == ["host-1"]
    sample = batch.metrics[0]
    assert sample.metric_key == "example.host.temperature_c"
    assert sample.entity_name == "esxi-a"
    # `at()` が timezone-aware なタイムスタンプを入れる（naive はバッチ全体の拒否になる）。
    assert sample.sampled_at.tzinfo is not None


async def test_the_sensor_setting_changes_the_value() -> None:
    """設定は経路によって型が違う（環境変数由来は常に str）ので config 経由で読む。"""
    si = FakeServiceInstance(hosts=[fake_host("host-1", "esxi-a")])
    first = await run_collect(TemperatureCollector(), connection=si)
    second = await run_collect(
        TemperatureCollector(), connection=si, config={"sensor": "cpu-die"}
    )
    assert first.metrics[0].value != second.metrics[0].value


async def test_mock_mode_never_opens_a_connection() -> None:
    batch = await run_collect(
        TemperatureCollector(),
        mock_mode=True,
        connection=failing_connection(AssertionError("must not connect")),
    )
    assert batch.metrics


async def test_the_fault_switch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """プロセス分離の確認に使う障害注入。例外の詳細はアプリの外へは出ない。"""
    monkeypatch.setenv("EXAMPLE_COLLECTOR_FAULT", "raise")
    with pytest.raises(RuntimeError):
        await run_collect(TemperatureCollector(), mock_mode=True)
