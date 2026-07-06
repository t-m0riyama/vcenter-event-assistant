"""POST /api/ingest/run の統合テスト。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.services.ingest_runner import IngestRunResult


@pytest.mark.asyncio
async def test_run_ingest_returns_counts(client: AsyncClient) -> None:
    with patch(
        "vcenter_event_assistant.api.routes.ingest.run_ingest_all",
        new=AsyncMock(
            return_value=IngestRunResult(events_inserted=3, metrics_inserted=5),
        ),
    ) as mock_run:
        r = await client.post("/api/ingest/run")

    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "events_inserted": 3,
        "metrics_inserted": 5,
    }
    mock_run.assert_awaited_once()
    settings_arg = mock_run.await_args.args[0]
    assert settings_arg is not None


@pytest.mark.asyncio
async def test_run_ingest_returns_409_when_busy(client: AsyncClient) -> None:
    from vcenter_event_assistant.services.ingest_runner import IngestBusyError

    with patch(
        "vcenter_event_assistant.api.routes.ingest.run_ingest_all",
        new=AsyncMock(side_effect=IngestBusyError()),
    ):
        r = await client.post("/api/ingest/run")

    assert r.status_code == 409
    assert r.json()["detail"] == "ingest already running"


@pytest.mark.asyncio
async def test_run_ingest_all_passes_settings_to_ingest_functions() -> None:
    """オーケストレータが settings を取り込みバッチに渡すことを確認する。"""
    from vcenter_event_assistant.settings import Settings
    from vcenter_event_assistant.services.ingest_runner import run_ingest_all

    settings = Settings()

    with patch(
        "vcenter_event_assistant.services.ingest_runner.ingest_for_enabled_vcenters",
        new=AsyncMock(side_effect=[2, 4]),
    ) as mock_batch:
        result = await run_ingest_all(settings)

    assert result == IngestRunResult(events_inserted=2, metrics_inserted=4)
    assert mock_batch.await_count == 2
    assert mock_batch.await_args_list[0].args[0] is settings
    assert mock_batch.await_args_list[1].args[0] is settings


@pytest.mark.asyncio
async def test_run_ingest_all_rejects_when_already_running() -> None:
    from vcenter_event_assistant.settings import Settings
    from vcenter_event_assistant.services.ingest_runner import (
        IngestBusyError,
        _ingest_run_slot,
        run_ingest_all,
    )

    settings = Settings()

    async with _ingest_run_slot(policy="reject"):
        with pytest.raises(IngestBusyError):
            await run_ingest_all(settings)


@pytest.mark.asyncio
async def test_run_ingest_events_skips_when_busy() -> None:
    from vcenter_event_assistant.settings import Settings
    from vcenter_event_assistant.services.ingest_runner import (
        _ingest_run_slot,
        run_ingest_events,
    )

    settings = Settings()

    with patch(
        "vcenter_event_assistant.services.ingest_runner.ingest_for_enabled_vcenters",
        new=AsyncMock(return_value=9),
    ) as mock_batch:
        async with _ingest_run_slot(policy="reject"):
            result = await run_ingest_events(settings)

    assert result is None
    mock_batch.assert_not_awaited()
