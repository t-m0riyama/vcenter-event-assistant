"""イベントコレクタ（collectors/events.py）のテスト。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pyVmomi import vim
from sqlalchemy import select

from vcenter_event_assistant.collectors.events import (
    fetch_events_blocking,
    fetch_events_from_connection_blocking,
    normalize_event,
)
from vcenter_event_assistant.db.models import EventRecord, EventScoreRule, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins.registry import build_collector_registry, set_collector_registry
from vcenter_event_assistant.rules.notable import score_event
from vcenter_event_assistant.services.ingest_runner import run_ingest_events
from vcenter_event_assistant.settings import get_settings

_APD_EVENT_TYPE = "esx.problem.storage.apd.start"


def _event_ex(event_type_id: str = "") -> vim.event.EventEx:
    return vim.event.EventEx(
        key=1,
        chainId=1,
        createdTime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fullFormattedMessage="m",
        eventTypeId=event_type_id,
    )


def _event_with_key(key: int) -> SimpleNamespace:
    return SimpleNamespace(
        createdTime=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        fullFormattedMessage=f"event key={key}",
        key=key,
    )


def test_normalize_event_returns_none_when_key_attribute_missing() -> None:
    event = SimpleNamespace(
        createdTime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fullFormattedMessage="no key attribute",
    )
    assert normalize_event(event) is None


def test_normalize_event_returns_none_when_key_is_none() -> None:
    event = SimpleNamespace(
        createdTime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fullFormattedMessage="key is none",
        key=None,
    )
    assert normalize_event(event) is None


def test_normalize_event_accepts_vmware_key_zero() -> None:
    row = normalize_event(_event_with_key(0))
    assert row is not None
    assert row["vmware_key"] == 0


def test_normalize_event_maps_fields() -> None:
    row = normalize_event(_event_with_key(42))
    assert row is not None
    assert row["vmware_key"] == 42
    assert row["event_type"] == "SimpleNamespace"
    assert row["message"] == "event key=42"


@pytest.mark.parametrize(
    ("event_type_id", "expected"),
    [
        (_APD_EVENT_TYPE, _APD_EVENT_TYPE),
        ("", "vim.event.EventEx"),
        (" \t ", "vim.event.EventEx"),
        ("a" * 513, "vim.event.EventEx"),
        (f"  {_APD_EVENT_TYPE}\t", _APD_EVENT_TYPE),
        (" " + "a" * 512 + " ", "a" * 512),
    ],
    ids=["id", "empty", "blank", "too-long", "padded", "max-length-after-strip"],
)
def test_normalize_event_ex_type(event_type_id: str, expected: str) -> None:
    row = normalize_event(_event_ex(event_type_id))
    assert row is not None
    assert row["event_type"] == expected


def test_normalize_event_uses_class_name_for_non_string_id() -> None:
    event = _event_with_key(1)
    event.eventTypeId = 123

    row = normalize_event(event)

    assert row is not None
    assert row["event_type"] == "SimpleNamespace"


def test_normalize_magic_mock_uses_class_name() -> None:
    event = MagicMock(
        key=1,
        createdTime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fullFormattedMessage="m",
    )

    row = normalize_event(event)

    assert row is not None
    assert row["event_type"] == "MagicMock"


def test_normalize_extended_event_type() -> None:
    event = vim.event.ExtendedEvent(
        key=1,
        chainId=1,
        createdTime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fullFormattedMessage="m",
        eventTypeId="com.vmware.vc.HA.Foo",
    )
    row = normalize_event(event)
    assert row is not None
    assert row["event_type"] == "com.vmware.vc.HA.Foo"
    assert row["severity"] is None


def test_normalize_regular_vmware_event_type() -> None:
    event = vim.event.VmPoweredOnEvent(
        key=1,
        chainId=1,
        createdTime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fullFormattedMessage="m",
    )
    row = normalize_event(event)
    assert row is not None
    assert row["event_type"] == "vim.event.VmPoweredOnEvent"


def test_normalize_host_connection_lost_event_scores_as_high_risk() -> None:
    event = vim.event.HostConnectionLostEvent(
        key=1,
        chainId=1,
        createdTime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fullFormattedMessage="m",
    )
    row = normalize_event(event)
    assert row is not None
    assert row["severity"] is None
    result = score_event(event_type=row["event_type"], severity=row["severity"], message=row["message"])
    assert result.score == 40
    assert "high_risk_type" in result.tags


def test_fetch_events_from_connection_uses_event_ex_id() -> None:
    event = _event_ex(_APD_EVENT_TYPE)
    mock_si = MagicMock()
    mock_collector = (
        mock_si.RetrieveContent.return_value.eventManager.CreateCollectorForEvents.return_value
    )
    mock_collector.ReadNextEvents.side_effect = [[event], []]

    rows, max_ts = fetch_events_from_connection_blocking(mock_si, since=None)

    assert [row["event_type"] for row in rows] == [_APD_EVENT_TYPE]
    assert max_ts == event.createdTime
    mock_collector.DestroyCollector.assert_called_once()


@pytest.mark.asyncio
@patch("vcenter_event_assistant.plugins.runtime.disconnect")
@patch("vcenter_event_assistant.plugins.runtime.connect_vcenter")
async def test_scheduled_ingestion_matches_event_ex_score_rule_by_id(
    mock_connect: MagicMock,
    _mock_disconnect: MagicMock,
    no_external_collectors: None,
) -> None:
    mock_collector = (
        mock_connect.return_value.RetrieveContent.return_value.eventManager
        .CreateCollectorForEvents.return_value
    )
    mock_collector.ReadNextEvents.side_effect = [[_event_ex(_APD_EVENT_TYPE)], []]
    settings = get_settings().model_copy(update={"mock_mode": False})

    async with session_scope() as session:
        vc = VCenter(
            id=uuid.uuid4(),
            name="ingest-event-ex",
            host="vc.example",
            username="u",
            password="p",
        )
        session.add_all([vc, EventScoreRule(event_type=_APD_EVENT_TYPE, score_delta=25)])
        await session.flush()
        vcenter_id = vc.id

    set_collector_registry(build_collector_registry(settings))
    try:
        inserted = await run_ingest_events(settings)
    finally:
        set_collector_registry(None)

    assert inserted == 1
    async with session_scope() as session:
        records = await session.scalars(select(EventRecord).where(EventRecord.vcenter_id == vcenter_id))
        saved = records.one()
    assert saved.collector_id == "builtin.vcenter.events"
    assert saved.event_type == _APD_EVENT_TYPE
    assert saved.notable_score == 25


def test_normalize_event_missing_key_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="vcenter_event_assistant.collectors.events")
    event = SimpleNamespace(
        createdTime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fullFormattedMessage="skip me",
    )
    assert normalize_event(event) is None
    assert any("missing vmware key" in r.message for r in caplog.records)


@patch("vcenter_event_assistant.collectors.events.disconnect")
@patch("vcenter_event_assistant.collectors.events.connect_vcenter")
def test_fetch_events_blocking_skips_events_without_key(
    mock_connect: MagicMock,
    _mock_disconnect: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="vcenter_event_assistant.collectors.events")
    mock_collector = MagicMock()
    mock_collector.ReadNextEvents.side_effect = [
        [
            _event_with_key(1),
            SimpleNamespace(
                createdTime=datetime(2026, 1, 1, tzinfo=timezone.utc),
                fullFormattedMessage="no key",
            ),
        ],
        [],
    ]
    mock_si = MagicMock()
    mock_si.RetrieveContent.return_value.eventManager.CreateCollectorForEvents.return_value = (
        mock_collector
    )
    mock_connect.return_value = mock_si

    rows, max_ts = fetch_events_blocking(
        host="vc.example",
        port=443,
        username="u",
        password="p",
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        max_pages=10,
    )

    assert len(rows) == 1
    assert rows[0]["vmware_key"] == 1
    assert max_ts is not None
    assert any("missing vmware key" in r.message for r in caplog.records)
    mock_collector.DestroyCollector.assert_called_once()


@patch("vcenter_event_assistant.collectors.events.disconnect")
@patch("vcenter_event_assistant.collectors.events.connect_vcenter")
def test_fetch_events_blocking_warns_when_max_pages_reached(
    mock_connect: MagicMock,
    _mock_disconnect: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="vcenter_event_assistant.collectors.events")
    mock_collector = MagicMock()
    mock_collector.ReadNextEvents.return_value = [_event_with_key(1)]
    mock_si = MagicMock()
    mock_si.RetrieveContent.return_value.eventManager.CreateCollectorForEvents.return_value = (
        mock_collector
    )
    mock_connect.return_value = mock_si

    fetch_events_blocking(
        host="vc.example",
        port=443,
        username="u",
        password="p",
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        max_pages=2,
    )

    assert mock_collector.ReadNextEvents.call_count == 2
    assert any(
        "event fetch hit max_pages=2" in r.message and "host=vc.example" in r.message
        for r in caplog.records
    )


@patch("vcenter_event_assistant.collectors.events.disconnect")
@patch("vcenter_event_assistant.collectors.events.connect_vcenter")
def test_fetch_events_blocking_does_not_warn_when_pages_exhausted_early(
    mock_connect: MagicMock,
    _mock_disconnect: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="vcenter_event_assistant.collectors.events")
    mock_collector = MagicMock()
    mock_collector.ReadNextEvents.side_effect = [[_event_with_key(1)], []]
    mock_si = MagicMock()
    mock_si.RetrieveContent.return_value.eventManager.CreateCollectorForEvents.return_value = (
        mock_collector
    )
    mock_connect.return_value = mock_si

    fetch_events_blocking(
        host="vc.example",
        port=443,
        username="u",
        password="p",
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        max_pages=100,
    )

    assert not any("event fetch hit max_pages" in r.message for r in caplog.records)
