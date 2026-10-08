"""IncidentTimelineGraphContext（スナップショット用グラフ再生メタ）の単体テスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from vcenter_event_assistant.api.schemas.chat import (
    IncidentTimelineGraphCapturedRange,
    IncidentTimelineGraphContext,
)


def test_graph_context_accepts_empty_object() -> None:
    ctx = IncidentTimelineGraphContext.model_validate({})
    assert ctx.metric_key is None
    assert ctx.chart_event_type is None
    assert ctx.marker_timestamp_utc is None
    assert ctx.vcenter_id is None
    assert ctx.captured_range is None


def test_graph_context_accepts_full_payload() -> None:
    vid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    marker = datetime(2026, 3, 22, 6, 30, tzinfo=timezone.utc)
    raw = {
        "metric_key": "host.cpu.usage_pct",
        "chart_event_type": "VmPoweredOnEvent",
        "marker_timestamp_utc": marker.isoformat().replace("+00:00", "Z"),
        "vcenter_id": str(vid),
        "captured_range": {"from": t0.isoformat().replace("+00:00", "Z"), "to": t1.isoformat().replace("+00:00", "Z")},
    }
    ctx = IncidentTimelineGraphContext.model_validate(raw)
    assert ctx.metric_key == "host.cpu.usage_pct"
    assert ctx.chart_event_type == "VmPoweredOnEvent"
    assert ctx.marker_timestamp_utc == marker
    assert ctx.vcenter_id == vid
    assert ctx.captured_range is not None
    assert ctx.captured_range.from_time == t0
    assert ctx.captured_range.to_time == t1


def test_graph_context_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        IncidentTimelineGraphContext.model_validate({"extra_field": "x"})


def test_graph_context_rejects_metric_key_too_long() -> None:
    with pytest.raises(ValidationError):
        IncidentTimelineGraphContext.model_validate({"metric_key": "x" * 513})


def test_captured_range_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        IncidentTimelineGraphCapturedRange.model_validate(
            {
                "from": "2026-03-22T00:00:00Z",
                "to": "2026-03-23T00:00:00Z",
                "oops": 1,
            },
        )
