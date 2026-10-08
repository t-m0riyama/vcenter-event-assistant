"""イベントコレクタ（collectors/events.py）のテスト。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from vcenter_event_assistant.collectors.events import fetch_events_blocking, normalize_event


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
