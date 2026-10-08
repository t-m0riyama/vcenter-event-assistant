"""Tests for datastore summary metrics."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from vcenter_event_assistant.collectors.datastore_metrics import datastore_space_rows_from_datastores


def test_datastore_space_rows_used_pct_and_bytes() -> None:
    sampled = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
    ds = SimpleNamespace(
        _moId="ds-1",
        name="ds-a",
        summary=SimpleNamespace(capacity=1000, freeSpace=250),
    )
    rows = datastore_space_rows_from_datastores([ds], sampled_at=sampled)
    by_key = {r["metric_key"]: r["value"] for r in rows}
    assert by_key["datastore.space.used_pct"] == 75.0
    assert by_key["datastore.space.used_bytes"] == 750.0
    assert all(r["entity_type"] == "Datastore" for r in rows)
    assert rows[0]["entity_moid"] == "ds-1"


def test_datastore_space_skips_zero_capacity() -> None:
    sampled = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
    bad = SimpleNamespace(
        _moId="ds-bad",
        name="bad",
        summary=SimpleNamespace(capacity=0, freeSpace=0),
    )
    rows = datastore_space_rows_from_datastores([bad], sampled_at=sampled)
    assert rows == []
