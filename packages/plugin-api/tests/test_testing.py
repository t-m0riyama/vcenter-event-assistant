"""Tests for the plugin author's test harness."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectionContext,
    EventCollector,
    EventInput,
    MetricCollector,
    MetricDefinition,
)
from vcenter_event_assistant_plugin_api.testing import (
    ConnectionLeakError,
    FakeServiceInstance,
    StubCollector,
    ViewLeakError,
    assert_batch_valid,
    assert_manifest_valid,
    fake_datastore,
    fake_host,
    failing_connection,
    make_context,
    make_target,
    recording_connection,
    run_collect,
    stub_manifest,
    stub_plugin_source,
)

TEMPERATURE = MetricDefinition(
    key="example.host.temperature_c",
    display_name="Host temperature",
    unit="C",
    entity_type="HostSystem",
)


class Temperature(MetricCollector):
    """`vmware` ヘルパを使わず、si を直接読むコレクタ。"""

    id = "example.host.temperature"
    display_name = "Example Temperature"
    version = "0.1.0"
    metrics = (TEMPERATURE,)

    def sample(self, si: Any, context: CollectionContext) -> Any:
        for host in si.objects_of("HostSystem"):
            yield TEMPERATURE.at(
                entity_moid=host._moId, entity_name=host.name, value=31.5
            )


class TestMakeContext:
    def test_defaults_provide_a_working_connection(self) -> None:
        """既定で接続が開ける。`lambda: None` を置くと非 mock 経路が試せない。"""
        context = make_context()
        assert context.mock_mode is False
        assert context.previous_cursor is None
        assert callable(context.open_vcenter_connection)

    async def test_an_object_is_wrapped_into_a_connection(self) -> None:
        si = FakeServiceInstance()
        context = make_context(connection=si)
        async with context.open_vcenter_connection() as opened:
            assert opened is si

    async def test_a_factory_is_used_as_is(self) -> None:
        si = FakeServiceInstance()
        factory, log = recording_connection(si)
        context = make_context(connection=factory)
        async with context.open_vcenter_connection():
            pass
        assert (log.enters, log.exits) == (1, 1)

    def test_config_is_copied_so_the_caller_cannot_mutate_it(self) -> None:
        config = {"sensor": "system-board"}
        context = make_context(config=config)
        config["sensor"] = "changed"
        assert context.config["sensor"] == "system-board"

    def test_target_defaults_are_overridable(self) -> None:
        target = make_target(name="Alpha", host="vc1.example.com", verify_ssl=False)
        assert (target.name, target.host, target.verify_ssl) == (
            "Alpha",
            "vc1.example.com",
            False,
        )
        # id は毎回異なる（同じ値を使い回して取り違えないため）。
        assert make_target().id != make_target().id


class TestFakeServiceInstance:
    def test_container_view_returns_the_requested_types(self) -> None:
        si = FakeServiceInstance(
            hosts=[fake_host("host-1", "esxi-a")],
            datastores=[fake_datastore("ds-1", "store-a")],
        )
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(
            content.rootFolder, ["HostSystem"], True
        )
        assert [obj.name for obj in view.view] == ["esxi-a"]
        view.Destroy()
        assert view.destroyed is True

    def test_records_the_view_arguments(self) -> None:
        si = FakeServiceInstance()
        content = si.RetrieveContent()
        content.viewManager.CreateContainerView(content.rootFolder, ["Datastore"], False)
        root, type_names, recursive = si.view_calls[0]
        assert root is si.root_folder
        assert type_names == ("Datastore",)
        assert recursive is False

    def test_accepts_pyvmomi_types_as_well_as_names(self) -> None:
        """`vmware.container_view` は名前を pyVmomi の型に解決してから渡してくる。"""

        class _VimHostSystem:
            __name__ = "vim.HostSystem"

        si = FakeServiceInstance(hosts=[fake_host("host-1", "esxi-a")])
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(
            content.rootFolder, [_VimHostSystem()], True
        )
        assert [obj.name for obj in view.view] == ["esxi-a"]

    def test_assert_all_views_destroyed_names_the_leak(self) -> None:
        si = FakeServiceInstance()
        content = si.RetrieveContent()
        content.viewManager.CreateContainerView(content.rootFolder, ["HostSystem"], True)
        with pytest.raises(ViewLeakError, match="HostSystem"):
            si.assert_all_views_destroyed()

    def test_custom_object_types(self) -> None:
        si = FakeServiceInstance(objects={"ClusterComputeResource": [fake_host("c-1", "cl")]})
        assert [obj.name for obj in si.objects_of("ClusterComputeResource")] == ["cl"]

    def test_fake_host_carries_the_connection_state(self) -> None:
        assert fake_host().runtime.connectionState == "connected"
        assert fake_host(connected=False).runtime.connectionState == "disconnected"

    def test_fake_datastore_carries_a_summary(self) -> None:
        ds = fake_datastore(capacity=100, free_space=40)
        assert (ds.summary.capacity, ds.summary.freeSpace, ds.summary.accessible) == (
            100,
            40,
            True,
        )


class TestRunCollect:
    async def test_runs_the_lifecycle_and_returns_the_batch(self) -> None:
        plugin = StubCollector()
        batch = await run_collect(plugin)
        assert (plugin.start_count, plugin.stop_count, plugin.collect_count) == (1, 1, 1)
        assert batch.next_cursor == "cursor-1"

    async def test_calls_stop_even_when_collect_fails(self) -> None:
        plugin = StubCollector(fault="raise")
        with pytest.raises(RuntimeError):
            await run_collect(plugin)
        assert plugin.stop_count == 1

    async def test_reads_from_the_fake_service_instance(self) -> None:
        si = FakeServiceInstance(hosts=[fake_host("host-1", "esxi-a")])
        batch = await run_collect(Temperature(), connection=si)
        assert [sample.entity_moid for sample in batch.metrics] == ["host-1"]

    async def test_detects_a_leaked_connection(self) -> None:
        """接続を開いたまま返すコレクタを捕まえる。"""

        class Leaky(MetricCollector):
            id = "example.leaky"
            display_name = "Leaky"
            version = "0.1.0"
            metrics = (TEMPERATURE,)

            async def collect(self, context: CollectionContext) -> CollectionBatch:
                manager = context.open_vcenter_connection()
                await manager.__aenter__()  # 対応する __aexit__ が無い
                return CollectionBatch()

        with pytest.raises(ConnectionLeakError, match="left open"):
            await run_collect(Leaky())

    async def test_detects_an_undestroyed_view(self) -> None:
        class Forgetful(MetricCollector):
            id = "example.forgetful"
            display_name = "Forgetful"
            version = "0.1.0"
            metrics = (TEMPERATURE,)

            def sample(self, si: Any, context: CollectionContext) -> Any:
                content = si.RetrieveContent()
                content.viewManager.CreateContainerView(
                    content.rootFolder, ["HostSystem"], True
                )
                return ()

        with pytest.raises(ViewLeakError, match="not destroyed"):
            await run_collect(Forgetful(), connection=FakeServiceInstance())

    async def test_mock_mode_does_not_open_a_connection(self) -> None:
        batch = await run_collect(
            Temperature(),
            mock_mode=True,
            connection=failing_connection(AssertionError("must not connect")),
        )
        assert batch.metrics

    async def test_validation_rejects_an_undeclared_metric_key(self) -> None:
        plugin = StubCollector(
            batches=[
                CollectionBatch(
                    metrics=(
                        MetricDefinition("other.key", "Other", "C", "HostSystem").at(
                            entity_moid="host-1", entity_name="esxi-a", value=1.0
                        ),
                    )
                )
            ]
        )
        with pytest.raises(AssertionError, match="undeclared metric key"):
            await run_collect(plugin)

    async def test_validation_can_be_skipped(self) -> None:
        plugin = StubCollector(
            batches=[CollectionBatch(events=(_event(1),))]  # data_kinds は metric のみ
        )
        batch = await run_collect(plugin, validate=False)
        assert batch.events

    async def test_context_and_keyword_arguments_are_exclusive(self) -> None:
        with pytest.raises(TypeError, match="either context or"):
            await run_collect(StubCollector(), make_context(), mock_mode=True)

    async def test_an_explicit_context_is_still_checked(self) -> None:
        """自分で作った context を渡しても、接続とビューの検査は働く。"""
        si = FakeServiceInstance(hosts=[fake_host("host-1", "esxi-a")])
        batch = await run_collect(Temperature(), make_context(connection=si))
        assert len(batch.metrics) == 1

    async def test_batches_are_returned_in_order_then_repeat(self) -> None:
        first = CollectionBatch(next_cursor="a")
        second = CollectionBatch(next_cursor="b")
        plugin = StubCollector(batches=[first, second])
        assert (await run_collect(plugin)).next_cursor == "a"
        assert (await plugin.collect(make_context())).next_cursor == "b"
        assert (await plugin.collect(make_context())).next_cursor == "b"

    async def test_records_the_context_it_was_given(self) -> None:
        plugin = StubCollector()
        await run_collect(plugin, config={"sensor": "cpu"}, previous_cursor="c1")
        assert plugin.contexts[0].config == {"sensor": "cpu"}
        assert plugin.contexts[0].previous_cursor == "c1"


def _event(key: int, *, occurred_at: datetime | None = None) -> EventInput:
    return EventInput(
        occurred_at=occurred_at or datetime.now(timezone.utc),
        event_type="VmPoweredOnEvent",
        message="powered on",
        vmware_key=key,
    )


class TestAssertBatchValid:
    def test_accepts_a_valid_batch(self) -> None:
        manifest = stub_manifest()
        batch = CollectionBatch(
            metrics=(
                manifest.metric_definitions[0].at(
                    entity_moid="host-1", entity_name="esxi-a", value=1.0
                ),
            )
        )
        assert_batch_valid(manifest, batch)

    def test_warnings_fail_by_default(self) -> None:
        """本番では拒否されないが、放置するとデータが静かに消えるもの。"""
        manifest = stub_manifest(data_kinds=frozenset({"event"}), metric_definitions=())
        batch = CollectionBatch(events=(_event(1), _event(1)))  # バッチ内で重複
        with pytest.raises(AssertionError, match="warning"):
            assert_batch_valid(manifest, batch)
        assert_batch_valid(manifest, batch, allow_warnings=True)

    def test_errors_fail_even_when_warnings_are_allowed(self) -> None:
        manifest = stub_manifest()
        naive = MetricDefinition("example.host.temperature_c", "T", "C", "HostSystem").at(
            entity_moid="host-1",
            entity_name="esxi-a",
            value=1.0,
            sampled_at=datetime(2026, 1, 1),  # noqa: DTZ001 - naive を意図的に作る
        )
        batch = CollectionBatch(metrics=(naive,))
        with pytest.raises(AssertionError, match="timezone-aware"):
            assert_batch_valid(manifest, batch, allow_warnings=True)

    def test_assert_manifest_valid(self) -> None:
        assert_manifest_valid(stub_manifest())
        with pytest.raises(AssertionError, match="manifest is not valid"):
            assert_manifest_valid(stub_manifest(id="Not A Valid Id"))


class TestEventCollectorSupport:
    async def test_the_cursor_advances_on_an_empty_batch(self) -> None:
        class Events(EventCollector):
            id = "example.events"
            display_name = "Events"
            version = "0.1.0"

            def fetch(self, si: Any, context: CollectionContext, *, since: Any) -> Any:
                return ()

        batch = await run_collect(Events())
        assert batch.next_cursor is not None

    async def test_fetch_receives_the_window_start(self) -> None:
        seen: list[Any] = []
        previous = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

        class Events(EventCollector):
            id = "example.events2"
            display_name = "Events"
            version = "0.1.0"

            def fetch(self, si: Any, context: CollectionContext, *, since: Any) -> Any:
                seen.append(since)
                return (_event(7, occurred_at=previous + timedelta(minutes=5)),)

        batch = await run_collect(Events(), previous_cursor=previous.isoformat())
        assert seen[0] == previous - timedelta(seconds=1)
        assert batch.events[0].vmware_key == 7


class TestStubPluginSource:
    def test_the_generated_module_builds_a_working_collector(self, tmp_path: Any) -> None:
        module = tmp_path / "stub_collector.py"
        module.write_text(stub_plugin_source(), encoding="utf-8")
        code = (
            "import asyncio, sys;"
            f"sys.path.insert(0, {str(tmp_path)!r});"
            "import stub_collector;"
            "from vcenter_event_assistant_plugin_api.testing import run_collect;"
            "b = asyncio.run(run_collect(stub_collector.build_collector()));"
            "assert b.next_cursor == 'cursor-1', b;"
            "assert b.metrics[0].value == 42.5, b"
        )
        subprocess.run([sys.executable, "-c", code], check=True)

    def test_the_fault_switch_is_only_present_when_asked(self) -> None:
        assert "MODE" not in stub_plugin_source()
        source = stub_plugin_source(fault_env_var="VEA_TEST_PLUGIN_MODE")
        assert "VEA_TEST_PLUGIN_MODE" in source
        assert "os._exit(9)" in source

    def test_an_empty_batch_can_be_requested(self) -> None:
        source = stub_plugin_source(emit_metric=False, next_cursor=None)
        assert "metrics=(" not in source
        assert "next_cursor=None" in source

    def test_the_generated_source_is_importable_on_its_own(self, tmp_path: Any) -> None:
        """plugin-api 以外を import しないこと（プラグインの規約）。"""
        source = stub_plugin_source(fault_env_var="X", noisy_stdout=True)
        compile(source, "stub_collector.py", "exec")
        assert "vcenter_event_assistant." not in source


def test_the_harness_does_not_import_pytest() -> None:
    """本体は stdlib だけで動く。pytest は `fixtures` だけが触る。"""
    code = (
        "import sys;"
        "import vcenter_event_assistant_plugin_api.testing;"
        "assert 'pytest' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


class TestFixtures:
    """`testing.fixtures` は opt-in である。"""

    def test_it_is_not_registered_as_a_pytest_plugin(self) -> None:
        """`pytest11` を登録すると、このパッケージを入れた全セッションに載ってしまう。"""
        from importlib.metadata import entry_points

        names = {ep.value for ep in entry_points(group="pytest11")}
        assert not any("vcenter_event_assistant_plugin_api" in name for name in names)

    def test_the_fixtures_work_when_loaded_explicitly(self, tmp_path: Any) -> None:
        (tmp_path / "conftest.py").write_text(
            'pytest_plugins = ["vcenter_event_assistant_plugin_api.testing.fixtures"]\n',
            encoding="utf-8",
        )
        (tmp_path / "pytest.ini").write_text(
            "[pytest]\nasyncio_mode = auto\n", encoding="utf-8"
        )
        (tmp_path / "test_generated.py").write_text(
            "from vcenter_event_assistant_plugin_api.testing import (\n"
            "    fake_host, run_collect, StubCollector,\n"
            ")\n"
            "\n"
            "def test_target_and_service_instance(target, service_instance):\n"
            "    assert target.host\n"
            "    assert service_instance.objects_of('HostSystem') == []\n"
            "\n"
            "async def test_context_reaches_the_service_instance(context, service_instance):\n"
            "    service_instance._objects['HostSystem'].append(fake_host())\n"
            "    async with context.open_vcenter_connection() as si:\n"
            "        assert si is service_instance\n"
            "\n"
            "async def test_mock_context_refuses_to_connect(mock_context):\n"
            "    assert mock_context.mock_mode is True\n"
            "    await run_collect(StubCollector(), mock_context)\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "3 passed" in completed.stdout
