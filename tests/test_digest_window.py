"""digest_window.utc_yesterday_window の境界テスト。"""

from __future__ import annotations

from datetime import datetime, timezone

from vcenter_event_assistant.services.digest_window import utc_yesterday_window


def test_yesterday_window_mid_march() -> None:
    now = datetime(2026, 3, 23, 7, 30, 0, tzinfo=timezone.utc)
    fr, to = utc_yesterday_window(now)
    assert fr == datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    assert fr < to
