"""aggregation_limiter の同時実行数の上限のテスト。"""

from __future__ import annotations

import pytest

from vcenter_event_assistant.services.chat.aggregation_limiter import (
    AggregationBusy,
    aggregation_slot,
)


def test_per_owner_limit_rejects_second_slot_for_same_owner() -> None:
    with aggregation_slot("alice", global_limit=4, per_owner_limit=1):
        with pytest.raises(AggregationBusy):
            with aggregation_slot("alice", global_limit=4, per_owner_limit=1):
                pass
        with aggregation_slot("bob", global_limit=4, per_owner_limit=1):
            pass


def test_global_limit_rejects_other_owners() -> None:
    with aggregation_slot("a", global_limit=2, per_owner_limit=1):
        with aggregation_slot("b", global_limit=2, per_owner_limit=1):
            with pytest.raises(AggregationBusy):
                with aggregation_slot("c", global_limit=2, per_owner_limit=1):
                    pass


def test_slot_is_returned_after_exit_and_after_exception() -> None:
    with aggregation_slot("a", global_limit=1, per_owner_limit=1):
        pass
    with pytest.raises(RuntimeError):
        with aggregation_slot("a", global_limit=1, per_owner_limit=1):
            raise RuntimeError("boom")
    with aggregation_slot("a", global_limit=1, per_owner_limit=1):
        pass
