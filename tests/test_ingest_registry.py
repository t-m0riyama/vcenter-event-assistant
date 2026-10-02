"""Initialized-registry regressions for manual ingestion (Issue #229)."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from unittest.mock import AsyncMock, call

import pytest
from httpx import AsyncClient
from vcenter_event_assistant_plugin_api.testing import StubCollector, stub_manifest

from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins.config import CollectorConfig
from vcenter_event_assistant.plugins.registry import (
    CollectorRegistration,
    CollectorRegistry,
)
from vcenter_event_assistant.plugins.runtime import CollectorRunResult
from vcenter_event_assistant.services import ingest_runner
from vcenter_event_assistant.services.ingest_runner import (
    IngestRunResult,
    run_ingest_all,
)
from vcenter_event_assistant.settings import Settings


def registry_with_collectors(count: int) -> CollectorRegistry:
    if count == 0:
        return CollectorRegistry({})
    registrations = {}
    for index in range(count + 1):
        plugin_id = f"test.collector{index}"
        plugin = StubCollector(manifest=stub_manifest(id=plugin_id))
        enabled = index < count
        registrations[plugin_id] = CollectorRegistration(
            plugin_id,
            plugin,
            "test",
            CollectorConfig(enabled, 300),
            "enabled" if enabled else "disabled",
        )
    return CollectorRegistry(registrations)


@pytest.mark.parametrize("count", [0, 1, 3])
async def test_run_ingest_all_aggregates_enabled_collectors(
    monkeypatch, count: int
) -> None:
    settings = Settings(_env_file=None)
    registry = registry_with_collectors(count)
    expected_results = tuple(
        CollectorRunResult(f"test.collector{i}", "ok", j, 2 * j, logs_inserted=3 * j)
        for i in range(count)
        for j in (1, 2)
    )
    calls = []
    active = False

    async def run(settings_arg, plugin_id):
        nonlocal active
        assert settings_arg is settings
        assert not active
        active = True
        calls.append(plugin_id)
        await asyncio.sleep(0)
        active = False
        return tuple(
            result for result in expected_results if result.plugin_id == plugin_id
        )

    mock_run = AsyncMock(side_effect=run)
    fallback = AsyncMock()
    monkeypatch.setattr(ingest_runner, "get_collector_registry", lambda: registry)
    monkeypatch.setattr(ingest_runner, "run_registered_collector", mock_run)
    monkeypatch.setattr(ingest_runner, "ingest_for_enabled_vcenters", fallback)

    result = await run_ingest_all(settings)

    assert result == IngestRunResult(3 * count, 6 * count, expected_results, 9 * count)
    assert calls == [f"test.collector{i}" for i in range(count)]
    assert mock_run.await_args_list == [
        call(settings, plugin_id) for plugin_id in calls
    ]
    fallback.assert_not_awaited()


@pytest.mark.parametrize("scenario", ["empty", "no_targets", "ok", "partial"])
async def test_ingest_api_runs_registry_path(
    client: AsyncClient, monkeypatch, scenario: str
) -> None:
    count = 0 if scenario == "empty" else 3
    registry = registry_with_collectors(count)
    target_count = 0 if scenario == "no_targets" else 2
    async with session_scope() as session:
        vcenters = [
            VCenter(name=f"vc{i}", host=f"vc{i}.example", username="u", password="p")
            for i in range(target_count)
        ]
        session.add_all(vcenters)
        await session.flush()
        ids = [vc.id for vc in vcenters]

    expected_results = []
    for registration in registry.enabled():
        for vcenter_id in ids:
            failed = (
                scenario == "partial" and registration.plugin_id == "test.collector1"
            )
            expected_results.append(
                (
                    registration.plugin_id,
                    vcenter_id,
                    CollectorRunResult(
                        registration.plugin_id,
                        "failed" if failed else "ok",
                        0 if failed else 1,
                        0 if failed else 2,
                        error="collector execution failed" if failed else None,
                        logs_inserted=0 if failed else 3,
                    ),
                )
            )

    async def run(settings, registration, vcenter_id):
        return next(
            result
            for plugin_id, vid, result in expected_results
            if plugin_id == registration.plugin_id and vid == vcenter_id
        )

    mock_run = AsyncMock(side_effect=run)
    fallback = AsyncMock()
    monkeypatch.setattr(ingest_runner, "get_collector_registry", lambda: registry)
    monkeypatch.setattr(ingest_runner, "run_collector_for_vcenter", mock_run)
    monkeypatch.setattr(ingest_runner, "ingest_for_enabled_vcenters", fallback)

    response = await client.post("/api/ingest/run")

    assert response.status_code == 200
    results = [result for _, _, result in expected_results]
    expected = {
        "status": "partial" if scenario == "partial" else "ok",
        "events_inserted": sum(result.events_inserted for result in results),
        "metrics_inserted": sum(result.metrics_inserted for result in results),
        "logs_inserted": sum(result.logs_inserted for result in results),
    }
    if results:
        # vCenter query order is not part of the API contract. Each collector's
        # two targets produce identical results, so this still checks plugin order.
        expected["plugins"] = [asdict(result) for result in results]
    assert response.json() == expected
    assert mock_run.await_count == target_count * count
    assert {
        (args.args[1].plugin_id, args.args[2]) for args in mock_run.await_args_list
    } == {(plugin_id, vid) for plugin_id, vid, _ in expected_results}
    fallback.assert_not_awaited()


async def test_ingest_api_busy_uses_real_runner(client: AsyncClient) -> None:
    async with ingest_runner._ingest_run_slot(policy="reject"):
        response = await client.post("/api/ingest/run")
    assert response.status_code == 409
    assert response.json() == {"detail": "ingest already running"}


async def test_ingest_all_releases_slot_after_unexpected_error(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    registry = registry_with_collectors(1)
    monkeypatch.setattr(ingest_runner, "get_collector_registry", lambda: registry)
    mock_run = AsyncMock(side_effect=[RuntimeError("unexpected failure"), ()])
    monkeypatch.setattr(ingest_runner, "run_registered_collector", mock_run)

    with pytest.raises(RuntimeError, match="unexpected failure"):
        await run_ingest_all(settings)
    assert not ingest_runner._ingest_busy
    assert await run_ingest_all(settings) == IngestRunResult(0, 0)
    assert mock_run.await_count == 2
