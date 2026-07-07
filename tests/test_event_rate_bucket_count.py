"""event_rate_bucket_count のユニットテスト。"""

from datetime import datetime, timezone

from vcenter_event_assistant.services.event_repository import event_rate_bucket_count


def test_event_rate_bucket_count_aligns_to_series() -> None:
    ft = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    tt = datetime(2025, 1, 1, 0, 10, 0, tzinfo=timezone.utc)
    assert event_rate_bucket_count(ft, tt, 300) == 3


def test_event_rate_bucket_count_empty_when_to_before_first_bucket() -> None:
    ft = datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
    tt = datetime(2025, 1, 1, 0, 0, 2, tzinfo=timezone.utc)
    assert event_rate_bucket_count(ft, tt, 300) == 1
