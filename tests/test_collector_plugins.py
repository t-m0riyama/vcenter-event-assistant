from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectorManifest,
    MetricDefinition,
    MetricSampleInput,
)

from vcenter_event_assistant.db.models import (
    CollectorRunState,
    IngestionState,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins.config import CollectorConfig
from vcenter_event_assistant.plugins.registry import (
    CollectorRegistration,
    CollectorRegistry,
    build_collector_registry,
    set_collector_registry,
    start_collector_registry,
)
from vcenter_event_assistant.plugins.runtime import run_collector_for_vcenter
from vcenter_event_assistant.settings import Settings


class SampleCollector:
    manifest = CollectorManifest(
        "example.temperature",
        "Temperature",
        "2.1.0",
        data_kinds=frozenset({"metric"}),
        metric_definitions=(
            MetricDefinition(
                "example.host.temperature_c", "Temperature", "C", "HostSystem"
            ),
        ),
    )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def collect(self, context) -> CollectionBatch:
        return CollectionBatch(
            metrics=(
                MetricSampleInput(
                    datetime.now(timezone.utc),
                    "HostSystem",
                    "host-1",
                    "esxi-1",
                    "example.host.temperature_c",
                    42.5,
                ),
            ),
            next_cursor="cursor-1",
        )


def test_registry_contains_four_builtin_collectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vcenter_event_assistant.plugins.registry.entry_points", lambda **_: []
    )
    registry = build_collector_registry(Settings())
    assert {item.plugin_id for item in registry.enabled()} == {
        "builtin.vcenter.events",
        "builtin.vcenter.host_quickstats",
        "builtin.vcenter.host_performance",
        "builtin.vcenter.datastore_capacity",
    }
    assert {definition.key for _, definition in registry.metric_catalog()} >= {
        "host.cpu.usage_pct",
        "datastore.space.used_bytes",
    }


def test_registry_toml_can_disable_builtin_and_reports_missing_plugin(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "collectors.toml"
    config.write_text(
        '[collectors."builtin.vcenter.host_performance"]\nenabled = false\n'
        '[collectors."missing.plugin"]\nenabled = true\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.plugins.registry.entry_points", lambda **_: []
    )
    registry = build_collector_registry(Settings(collector_config_file=str(config)))
    assert registry.get("builtin.vcenter.host_performance").status == "disabled"
    assert registry.get("missing.plugin").status == "failed"


def test_collector_environment_overrides_toml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "collectors.toml"
    config.write_text(
        '[collectors."builtin.vcenter.events"]\nenabled = false\ninterval_seconds = 99\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VEA_COLLECTOR__BUILTIN_VCENTER_EVENTS__ENABLED", "true")
    monkeypatch.setenv("VEA_COLLECTOR__BUILTIN_VCENTER_EVENTS__INTERVAL_SECONDS", "45")
    monkeypatch.setattr(
        "vcenter_event_assistant.plugins.registry.entry_points", lambda **_: []
    )
    registration = build_collector_registry(
        Settings(collector_config_file=str(config))
    ).get("builtin.vcenter.events")
    assert registration.status == "enabled"
    assert registration.config.interval_seconds == 45


@pytest.mark.asyncio
async def test_start_failure_is_isolated() -> None:
    plugin = SampleCollector()

    async def fail() -> None:
        raise RuntimeError("broken")

    plugin.start = fail  # type: ignore[method-assign]
    registration = CollectorRegistration(
        plugin.manifest.id, plugin, "test", CollectorConfig(True, 300), "enabled"
    )
    started = await start_collector_registry(
        CollectorRegistry({plugin.manifest.id: registration})
    )
    assert started.get(plugin.manifest.id).status == "failed"
    assert "start failed" in started.get(plugin.manifest.id).error


@pytest.mark.asyncio
async def test_runtime_persists_declared_metric_cursor_and_state() -> None:
    plugin = SampleCollector()
    registration = CollectorRegistration(
        plugin.manifest.id, plugin, "test", CollectorConfig(True, 300), "enabled"
    )
    async with session_scope() as session:
        vcenter = VCenter(
            id=uuid.uuid4(),
            name="plugin-vc",
            host="vc.example",
            username="u",
            password="p",
        )
        session.add(vcenter)
        await session.flush()
        vcenter_id = vcenter.id

    result = await run_collector_for_vcenter(
        Settings(mock_mode=True), registration, vcenter_id
    )
    assert result.status == "ok"
    assert result.metrics_inserted == 1
    async with session_scope() as session:
        sample = (await session.execute(select(MetricSample))).scalar_one()
        state = (await session.execute(select(CollectorRunState))).scalar_one()
        cursor = (await session.execute(select(IngestionState))).scalar_one()
    assert sample.collector_id == "example.temperature"
    assert state.status == "ok"
    assert cursor.cursor_value == "cursor-1"


@pytest.mark.asyncio
async def test_collector_status_and_metric_catalog_api(client) -> None:
    plugin = SampleCollector()
    registration = CollectorRegistration(
        plugin.manifest.id, plugin, "test", CollectorConfig(True, 300), "enabled"
    )
    set_collector_registry(
        CollectorRegistry({plugin.manifest.id: registration}, generation=7)
    )
    try:
        catalog = await client.get("/api/metrics/catalog")
        status = await client.get("/api/plugins/collectors")
    finally:
        set_collector_registry(None)
    assert catalog.json()["metrics"][0]["key"] == "example.host.temperature_c"
    assert status.json()["generation"] == 7
    assert status.json()["collectors"][0]["id"] == "example.temperature"
