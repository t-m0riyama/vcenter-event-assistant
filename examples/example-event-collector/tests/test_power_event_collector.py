"""サンプルイベントコレクタの単体テスト。

アプリを起動せず、vCenter も用意せずに ``pytest`` だけで通る。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from vcenter_event_assistant_plugin_api.testing import (
    FakeServiceInstance,
    assert_manifest_valid,
    fake_event,
    fake_host,
    run_collect,
)

from example_event_collector import (
    DEFAULT_EVENT_TYPES,
    PLUGIN_ID,
    PowerEventCollector,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_the_manifest_matches_the_entry_point_name() -> None:
    manifest = PowerEventCollector.manifest
    assert manifest.id == PLUGIN_ID
    assert manifest.data_kinds == frozenset({"event"})
    assert_manifest_valid(manifest)


async def test_it_converts_events_with_the_natural_key() -> None:
    now = _now()
    si = FakeServiceInstance(
        events=[
            fake_event(
                101,
                event_type="VmPoweredOnEvent",
                created_time=now - timedelta(minutes=2),
                entity=fake_host("vm-1", "web-01"),
            ),
            fake_event(
                102,
                event_type="VmPoweredOffEvent",
                created_time=now - timedelta(minutes=1),
            ),
        ]
    )
    batch = await run_collect(PowerEventCollector(), connection=si)

    # vCenter が振った key をそのまま使う（ハッシュにすると重複排除で静かに消える）。
    assert [event.vmware_key for event in batch.events] == [101, 102]
    assert [event.event_type for event in batch.events] == [
        "VmPoweredOnEvent",
        "VmPoweredOffEvent",
    ]
    assert batch.events[0].entity_name == "web-01"
    assert batch.events[0].occurred_at.tzinfo is not None
    # イベントコレクタは破棄済み（`run_collect` も検査している）。
    assert all(collector.destroyed for collector in si.event_collectors)


async def test_it_asks_vcenter_only_for_the_declared_event_types() -> None:
    si = FakeServiceInstance()
    await run_collect(PowerEventCollector(), connection=si)
    assert si.event_filters[0].eventTypeId == list(DEFAULT_EVENT_TYPES)


async def test_the_event_types_can_be_configured() -> None:
    """設定は管理画面・TOML・環境変数から来る。環境変数由来は常に str である。"""
    si = FakeServiceInstance()
    await run_collect(
        PowerEventCollector(),
        connection=si,
        config={"event_types": "VmPoweredOnEvent, VmRemovedEvent"},
    )
    assert si.event_filters[0].eventTypeId == ["VmPoweredOnEvent", "VmRemovedEvent"]


async def test_the_cursor_advances_even_on_an_empty_batch() -> None:
    """前進しないと、同じ範囲を永久に読み直す。"""
    batch = await run_collect(PowerEventCollector(), connection=FakeServiceInstance())
    assert batch.events == ()
    assert batch.next_cursor is not None


async def test_the_cursor_advances_to_the_latest_event() -> None:
    latest = _now() - timedelta(minutes=1)
    si = FakeServiceInstance(
        events=[
            fake_event(1, created_time=latest - timedelta(minutes=5)),
            fake_event(2, created_time=latest),
        ]
    )
    batch = await run_collect(PowerEventCollector(), connection=si)
    assert batch.next_cursor == latest.isoformat()


async def test_the_window_start_steps_back_by_the_overlap() -> None:
    """境界上のイベントを取りこぼさないため、取得範囲の開始は 1 秒戻る。"""
    previous = _now() - timedelta(minutes=10)
    si = FakeServiceInstance()
    await run_collect(
        PowerEventCollector(), connection=si, previous_cursor=previous.isoformat()
    )
    assert si.event_filters[0].time.beginTime == previous - timedelta(seconds=1)


async def test_events_without_a_key_are_skipped_not_collapsed_to_zero() -> None:
    """key を 0 に潰すと、重複排除で 1 件しか残らない。"""
    keyless = fake_event(1)
    del keyless.key
    si = FakeServiceInstance(events=[keyless, fake_event(7)])

    batch = await run_collect(PowerEventCollector(), connection=si)
    assert [event.vmware_key for event in batch.events] == [7]


async def test_keys_outside_the_int32_range_are_skipped() -> None:
    """`EventRecord.vmware_key` は 32 bit である。範囲外は DB で失敗する。"""
    si = FakeServiceInstance(events=[fake_event(2**31), fake_event(9)])

    batch = await run_collect(PowerEventCollector(), connection=si)
    assert [event.vmware_key for event in batch.events] == [9]


@pytest.mark.parametrize("length", [2000])
async def test_a_long_entity_name_is_truncated_to_the_column_limit(length: int) -> None:
    si = FakeServiceInstance(
        events=[fake_event(11, entity=fake_host("vm-1", "x" * length))]
    )
    batch = await run_collect(PowerEventCollector(), connection=si)
    assert len(batch.events[0].entity_name) == 1024
