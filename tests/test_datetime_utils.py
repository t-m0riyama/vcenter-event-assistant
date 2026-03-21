"""Unit tests for ``vcenter_event_assistant.api.datetime_utils``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vcenter_event_assistant.api.datetime_utils import to_utc


def test_to_utc_naive_is_utc() -> None:
    dt = datetime(2024, 1, 15, 12, 0, 0)
    out = to_utc(dt)
    assert out.tzinfo == timezone.utc
    assert out == datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_to_utc_offset_converts_to_utc() -> None:
    jst = timezone(timedelta(hours=9))
    dt = datetime(2024, 1, 15, 21, 0, 0, tzinfo=jst)
    out = to_utc(dt)
    assert out == datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
