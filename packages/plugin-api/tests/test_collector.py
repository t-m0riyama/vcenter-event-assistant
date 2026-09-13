"""宣言的な基底クラス。

ここで確かめるのは「作者が書かなくてよくなったこと」が本当に基底で行われているか、
そして間違いが**クラス定義の時点で**分かるかである。
"""

from __future__ import annotations

from typing import Any

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectionContext,
    CollectorManifest,
    EventInput,
    ManifestValidationError,
    MetricDefinition,
    VCenterTarget,
)
from vcenter_event_assistant_plugin_api.collector import (
    CollectorBase,
    EventCollector,
    MetricCollector,
)
from vcenter_event_assistant_plugin_api.cursors import TimestampCursor

TEMPERATURE = MetricDefinition(
    key="example.host.temperature_c",
    display_name="Host temperature",
    unit="C",
    entity_type="HostSystem",
)


class _ConnectionLog:
    def __init__(self, si: object = "SI") -> None:
        self.si = si
        self.enters = 0
        self.exits = 0

    def factory(self):
        @asynccontextmanager
        async def _open():
            self.enters += 1
            try:
                yield self.si
            finally:
                self.exits += 1

        return _open()


def make_context(**overrides) -> CollectionContext:
    log = overrides.pop("_log", None) or _ConnectionLog()
    base = dict(
        target=VCenterTarget(uuid.uuid4(), "A", "vc.example", "https", 443, "u", True),
        config={},
        previous_cursor=None,
        open_vcenter_connection=log.factory,
        mock_mode=False,
    )
    base.update(overrides)
    return CollectionContext(**base)  # type: ignore[arg-type]


class Temperature(MetricCollector):
    id = "example.host.temperature"
    display_name = "Example Host Temperature"
    version = "0.1.0"
    metrics = (TEMPERATURE,)
    default_interval_seconds = 120

    def sample(self, si, context):
        yield TEMPERATURE.at(entity_moid=f"{si}-1", entity_name="esxi-01", value=31.5)


# --- manifest の自動生成 ---------------------------------------------------


def test_manifest_is_built_from_class_attributes() -> None:
    manifest = Temperature.manifest
    assert manifest.id == "example.host.temperature"
    assert manifest.display_name == "Example Host Temperature"
    assert manifest.version == "0.1.0"
    assert manifest.default_interval_seconds == 120
    assert manifest.metric_definitions == (TEMPERATURE,)


def test_description_defaults_to_empty() -> None:
    """説明は任意。書かなければ空文字で、画面には何も出ない。"""
    assert Temperature.manifest.description == ""


def test_data_kinds_is_derived_from_the_base_class() -> None:
    """書き忘れるとバッチが丸ごと拒否される宣言。手で書かせない。"""
    assert Temperature.manifest.data_kinds == frozenset({"metric"})


def test_api_version_defaults_to_the_contract_generation() -> None:
    assert Temperature.manifest.api_version == 1


def test_the_class_itself_works_as_the_zero_argument_factory() -> None:
    """entry point には `module:ClassName` と書ける。"""
    assert isinstance(Temperature(), Temperature)


def test_start_and_stop_are_provided() -> None:
    collector = Temperature()
    asyncio.run(collector.start())
    asyncio.run(collector.stop())


# --- 誤りはクラス定義の時点で落ちる ---------------------------------------


def test_a_missing_id_names_the_attribute() -> None:
    with pytest.raises(ManifestValidationError, match="must define 'id'"):

        class Broken(MetricCollector):
            display_name = "x"
            version = "1.0.0"
            metrics = (TEMPERATURE,)


def test_the_error_mentions_the_abstract_escape_hatch() -> None:
    with pytest.raises(ManifestValidationError, match="abstract = True"):

        class Broken(MetricCollector):
            display_name = "x"
            version = "1.0.0"


def test_an_invalid_id_is_caught_at_class_creation() -> None:
    with pytest.raises(ManifestValidationError, match="invalid plugin id"):

        class Broken(MetricCollector):
            id = "Example"  # 大文字は不可
            display_name = "x"
            version = "1.0.0"
            metrics = (TEMPERATURE,)


def test_a_metric_collector_without_definitions_is_caught() -> None:
    with pytest.raises(
        ManifestValidationError, match="must declare metric definitions"
    ):

        class Broken(MetricCollector):
            id = "a.b"
            display_name = "x"
            version = "1.0.0"


def test_intermediate_bases_are_skipped() -> None:
    class Shared(MetricCollector):
        abstract = True

        def helper(self) -> int:
            return 1

    class Concrete(Shared):
        id = "a.b"
        display_name = "x"
        version = "1.0.0"
        metrics = (TEMPERATURE,)

        def sample(self, si, context):
            return ()

    assert Concrete.manifest.id == "a.b"
    assert Concrete().helper() == 1


def test_abstract_does_not_leak_to_subclasses() -> None:
    """`abstract` はそのクラス自身の __dict__ だけを見る。継承したら中間扱いになってしまう。"""

    class Shared(MetricCollector):
        abstract = True

    with pytest.raises(ManifestValidationError):

        class Concrete(Shared):
            display_name = "x"  # id が無い → 具象として検査される
            version = "1.0.0"


def test_an_explicit_manifest_is_respected() -> None:
    """既存の書き方のまま基底だけ使える。一度に移行する必要はない。"""
    from vcenter_event_assistant_plugin_api import CollectorManifest

    class Explicit(CollectorBase):
        manifest = CollectorManifest(
            id="explicit.one",
            display_name="Explicit",
            version="2.0.0",
            data_kinds=frozenset({"event"}),
        )

    assert Explicit.manifest.version == "2.0.0"


def test_an_explicit_manifest_is_still_validated() -> None:
    from vcenter_event_assistant_plugin_api import CollectorManifest

    with pytest.raises(ManifestValidationError, match="invalid plugin id"):

        class Explicit(CollectorBase):
            manifest = CollectorManifest(
                id="BAD", display_name="x", version="1.0", data_kinds=frozenset({"event"})
            )


def test_collector_base_without_collect_says_what_to_implement() -> None:
    class Bare(CollectorBase):
        id = "a.b"
        display_name = "x"
        version = "1.0.0"
        data_kinds = frozenset({"event"})

    with pytest.raises(NotImplementedError, match="MetricCollector / EventCollector"):
        asyncio.run(Bare().collect(make_context()))


# --- MetricCollector の収集 -----------------------------------------------


async def test_the_base_opens_and_closes_the_connection() -> None:
    log = _ConnectionLog()
    batch = await Temperature().collect(make_context(_log=log))

    assert log.enters == 1
    assert log.exits == 1, "接続が閉じられていない"
    assert batch.metrics[0].entity_moid == "SI-1"


async def test_samples_are_complete_without_writing_the_key_twice() -> None:
    batch = await Temperature().collect(make_context())
    sample = batch.metrics[0]

    assert sample.metric_key == TEMPERATURE.key
    assert sample.entity_type == "HostSystem"
    assert sample.sampled_at.tzinfo is not None


async def test_mock_mode_never_opens_a_connection() -> None:
    log = _ConnectionLog()
    batch = await Temperature().collect(make_context(_log=log, mock_mode=True))

    assert log.enters == 0
    assert batch.metrics, "既定の合成データが空だと MOCK_MODE で画面に何も出ない"
    assert all(s.metric_key == TEMPERATURE.key for s in batch.metrics)
    assert all(s.sampled_at.tzinfo is not None for s in batch.metrics)


async def test_the_default_mock_data_is_deterministic() -> None:
    first = await Temperature().collect(make_context(mock_mode=True))
    second = await Temperature().collect(make_context(mock_mode=True))
    assert [s.value for s in first.metrics] == [s.value for s in second.metrics]


async def test_a_generator_sample_is_consumed_inside_the_thread() -> None:
    """スレッドの外でジェネレータを回すと、退避した意味がなくなる。"""
    import threading

    seen: list[int] = []

    class Threaded(MetricCollector):
        id = "a.threaded"
        display_name = "x"
        version = "1.0.0"
        metrics = (TEMPERATURE,)

        def sample(self, si, context):
            seen.append(threading.get_ident())
            yield TEMPERATURE.at(entity_moid="h", entity_name="n", value=1)

    await Threaded().collect(make_context())
    assert seen and seen[0] != threading.get_ident()


async def test_sample_must_be_implemented() -> None:
    class Unimplemented(MetricCollector):
        id = "a.unimplemented"
        display_name = "x"
        version = "1.0.0"
        metrics = (TEMPERATURE,)

    with pytest.raises(NotImplementedError, match="must implement sample"):
        await Unimplemented().collect(make_context())


# --- EventCollector のカーソル管理 ----------------------------------------


class Events(EventCollector):
    id = "example.events"
    display_name = "Example Events"
    version = "0.1.0"

    rows: tuple[EventInput, ...] = ()

    def fetch(self, si, context, *, since):
        self.seen_since = since
        return self.rows


def _event(when: datetime, key: int = 1) -> EventInput:
    return EventInput(occurred_at=when, event_type="T", message="m", vmware_key=key)


async def test_event_data_kinds_is_derived() -> None:
    assert Events.manifest.data_kinds == frozenset({"event"})


async def test_the_first_run_gets_no_window_start() -> None:
    collector = Events()
    await collector.collect(make_context())
    assert collector.seen_since is None


async def test_the_cursor_advances_to_the_newest_event() -> None:
    newest = datetime(2026, 2, 1, tzinfo=timezone.utc)
    collector = Events()
    collector.rows = (_event(datetime(2026, 1, 1, tzinfo=timezone.utc)), _event(newest, 2))

    batch = await collector.collect(make_context())
    assert batch.next_cursor == newest.isoformat()


async def test_the_next_window_steps_back_by_the_overlap() -> None:
    collector = Events()
    await collector.collect(make_context(previous_cursor="2026-01-01T00:00:00+00:00"))
    assert collector.seen_since == datetime(
        2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc
    )


async def test_an_empty_batch_still_advances_the_cursor() -> None:
    """前進しないと同じ範囲を永久に読み直す。"""
    previous = "2026-01-01T00:00:00+00:00"
    batch = await Events().collect(make_context(previous_cursor=previous))
    assert batch.next_cursor == previous


async def test_the_overlap_can_be_configured() -> None:
    class Wide(Events):
        id = "example.events.wide"
        cursor = TimestampCursor(overlap=timedelta(minutes=10))

    collector = Wide()
    await collector.collect(make_context(previous_cursor="2026-01-01T00:00:00+00:00"))
    assert collector.seen_since == datetime(
        2025, 12, 31, 23, 50, tzinfo=timezone.utc
    )


async def test_mock_events_are_empty_by_default() -> None:
    log = _ConnectionLog()
    batch = await Events().collect(make_context(_log=log, mock_mode=True))
    assert batch.events == ()
    assert log.enters == 0


async def test_fetch_must_be_implemented() -> None:
    class Unimplemented(EventCollector):
        id = "a.unimplemented_events"
        display_name = "x"
        version = "1.0.0"

    with pytest.raises(NotImplementedError, match="must implement fetch"):
        await Unimplemented().collect(make_context())


class TestSubclassingAConcreteCollector:
    """具象コレクタを継承して振る舞いだけ差し替える形（テストでよく書く）。"""

    def test_a_behaviour_only_subclass_inherits_the_manifest(self) -> None:
        class Parent(MetricCollector):
            id = "example.parent"
            display_name = "Parent"
            version = "1.0.0"
            metrics = (MetricDefinition("example.k", "K", "C", "HostSystem"),)

        class Child(Parent):
            async def collect(self, context: Any) -> CollectionBatch:
                return CollectionBatch()

        assert Child.manifest is Parent.manifest

    def test_declaring_anything_rebuilds_the_manifest(self) -> None:
        """`display_name` だけ変えた場合に、その変更が黙って失われないこと。"""

        class Parent(MetricCollector):
            id = "example.parent2"
            display_name = "Parent"
            version = "1.0.0"
            metrics = (MetricDefinition("example.k2", "K", "C", "HostSystem"),)

        class Child(Parent):
            display_name = "Child"

        assert Child.manifest.display_name == "Child"
        assert Child.manifest.id == "example.parent2"

    def test_declaring_only_a_description_rebuilds_the_manifest(self) -> None:
        """`description` だけ足した場合に、その宣言が黙って失われないこと。"""

        class Parent(MetricCollector):
            id = "example.parent3"
            display_name = "Parent"
            version = "1.0.0"
            metrics = (MetricDefinition("example.k3", "K", "C", "HostSystem"),)

        class Child(Parent):
            description = "ホストの温度を集める。"

        assert Child.manifest.description == "ホストの温度を集める。"
        assert Child.manifest.id == "example.parent3"

    def test_a_subclass_of_an_explicit_manifest_class_inherits_it(self) -> None:
        explicit = CollectorManifest(
            "example.explicit", "Explicit", "1.0.0", data_kinds=frozenset({"event"})
        )

        class Parent(CollectorBase):
            manifest = explicit

        class Child(Parent):
            pass

        assert Child.manifest is explicit

    def test_a_subclass_that_declares_nothing_and_has_no_manifest_still_fails(self) -> None:
        with pytest.raises(ManifestValidationError, match="must define 'id'"):

            class Nameless(MetricCollector):
                pass
