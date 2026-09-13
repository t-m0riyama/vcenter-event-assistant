"""組み込みコレクタを、偽の ServiceInstance で非 mock 経路のまま動かす。

これまで組み込みコレクタの検証は ``MOCK_MODE`` 経路か、収集関数を直接呼ぶ単体テストに
限られていた。ここでは ``plugin_api.testing.run_collect`` を使って、作者と**同じ道具**で
次をまとめて確かめる。

- 基底クラスが接続を開いて閉じること（リークが無いこと）
- ``CreateContainerView`` で作ったビューが ``Destroy()`` されること
- 返ってきたバッチがアプリの検証を通ること（warning も含めて）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from vcenter_event_assistant_plugin_api.testing import (
    FakeServiceInstance,
    fake_datastore,
    fake_event,
    fake_host,
    failing_connection,
    run_collect,
)

from vcenter_event_assistant.plugins.builtin import (
    DatastoreCapacityCollector,
    EventsCollector,
    HostQuickStatsCollector,
)


def _host_with_quickstats(moid: str, name: str, *, connected: bool = True):
    """``_host_metrics`` が読む属性を揃えたホスト。"""
    return fake_host(
        moid,
        name,
        connected=connected,
        summary=SimpleNamespace(
            quickStats=SimpleNamespace(overallCpuUsage=1000, overallMemoryUsage=1024),
            hardware=SimpleNamespace(cpuMhz=2000),
        ),
        hardware=SimpleNamespace(
            cpuInfo=SimpleNamespace(numCpuCores=4), memorySize=8 * 1024**3
        ),
    )


async def test_host_quickstats_collects_from_a_fake_service_instance() -> None:
    si = FakeServiceInstance(
        hosts=[
            _host_with_quickstats("host-1", "esxi-a"),
            _host_with_quickstats("host-2", "esxi-b", connected=False),
        ]
    )
    batch = await run_collect(HostQuickStatsCollector(), connection=si)

    # 切断中のホストは除かれる。
    assert {sample.entity_moid for sample in batch.metrics} == {"host-1"}
    assert {sample.metric_key for sample in batch.metrics} == {
        "host.cpu.usage_pct",
        "host.mem.usage_pct",
    }
    # CPU 1000MHz / (2000MHz * 4 コア) = 12.5%
    cpu = next(s for s in batch.metrics if s.metric_key == "host.cpu.usage_pct")
    assert cpu.value == 12.5
    # ビューは破棄済み（`run_collect` も検査しているが、意図を明示する）。
    assert all(view.destroyed for view in si.views)


async def test_datastore_capacity_collects_from_a_fake_service_instance() -> None:
    si = FakeServiceInstance(
        datastores=[
            fake_datastore("ds-1", "store-a", capacity=1000, free_space=250),
            # capacity 0 のデータストアはスキップされる（ゼロ除算を避ける既存の判定）。
            fake_datastore("ds-2", "store-b", capacity=0, free_space=0),
        ]
    )
    batch = await run_collect(DatastoreCapacityCollector(), connection=si)

    assert {sample.entity_moid for sample in batch.metrics} == {"ds-1"}
    used_pct = next(
        s for s in batch.metrics if s.metric_key == "datastore.space.used_pct"
    )
    assert used_pct.value == 75.0


async def test_events_collector_advances_the_cursor_on_an_empty_batch() -> None:
    """イベントが 1 件も無くてもカーソルは前進する（同じ範囲を読み続けないため）。"""
    si = FakeServiceInstance()
    batch = await run_collect(EventsCollector(), connection=si)

    assert batch.events == ()
    assert batch.next_cursor is not None
    # イベントコレクタは破棄済み（`run_collect` も検査している）。
    assert all(collector.destroyed for collector in si.event_collectors)


async def test_events_collector_normalizes_and_advances_to_the_latest_event() -> None:
    # カーソルが無い初回は「直近 1 日」を読むので、その範囲内の時刻にする。
    now = datetime.now(timezone.utc)
    first = now - timedelta(hours=2)
    latest = now - timedelta(hours=1)
    si = FakeServiceInstance(
        events=[
            fake_event(101, event_type="VmPoweredOnEvent", created_time=first),
            fake_event(102, event_type="VmPoweredOffEvent", created_time=latest),
        ]
    )
    batch = await run_collect(EventsCollector(), connection=si)

    assert [event.vmware_key for event in batch.events] == [101, 102]
    assert [event.event_type for event in batch.events] == [
        "VmPoweredOnEvent",
        "VmPoweredOffEvent",
    ]
    # カーソルは最新イベントの時刻まで進む。
    assert batch.next_cursor == latest.isoformat()


async def test_events_collector_asks_vcenter_for_the_overlapping_window() -> None:
    """カーソルは 1 秒だけ戻して渡す（境界上のイベントを取りこぼさないため）。"""
    previous = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    si = FakeServiceInstance(
        events=[fake_event(201, created_time=previous - timedelta(seconds=30))]
    )
    batch = await run_collect(
        EventsCollector(), connection=si, previous_cursor=previous.isoformat()
    )

    assert si.event_filters[0].time.beginTime == previous - timedelta(seconds=1)
    # 範囲外のイベントは vCenter 側で落ちるので、空バッチでもカーソルは後退しない。
    assert batch.events == ()
    assert batch.next_cursor == previous.isoformat()


async def test_mock_mode_never_opens_a_connection() -> None:
    """`MOCK_MODE=true` で接続を開こうとすれば、このテストが落ちる。"""
    batch = await run_collect(
        HostQuickStatsCollector(),
        mock_mode=True,
        connection=failing_connection(AssertionError("must not connect")),
    )
    assert batch.metrics
