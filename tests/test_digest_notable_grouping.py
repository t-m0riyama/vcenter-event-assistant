"""group_notable_rows_by_event_type の単体テスト（DB なし）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from vcenter_event_assistant.services.digest_context import (
    DigestContextEventSnippet,
    group_notable_rows_by_event_type,
)


def _snippet(
    *,
    id_: int,
    occurred_at: datetime,
    event_type: str,
    notable_score: int,
    message: str = "m",
    entity_name: str | None = "e1",
) -> DigestContextEventSnippet:
    return DigestContextEventSnippet(
        id=id_,
        vcenter_id=uuid.uuid4(),
        occurred_at=occurred_at,
        event_type=event_type,
        message=message,
        severity="info",
        entity_name=entity_name,
        notable_score=notable_score,
    )


def test_group_notable_rows_by_event_type_merges_same_type() -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    rows = [
        _snippet(id_=1, occurred_at=t0, event_type="TypeA", notable_score=15),
        _snippet(id_=2, occurred_at=t0 + timedelta(days=1), event_type="TypeA", notable_score=15),
        _snippet(id_=3, occurred_at=t0 + timedelta(days=2), event_type="TypeA", notable_score=15),
    ]
    groups = group_notable_rows_by_event_type(rows)
    assert len(groups) == 1
    g = groups[0]
    assert g.event_type == "TypeA"
    assert g.occurrence_count == 3
    assert g.occurred_at_first == t0
    assert g.occurred_at_last == t0 + timedelta(days=2)
    assert g.notable_score == 15
    assert g.message == "m"
    assert g.entity_name == "e1"


def test_group_notable_rows_by_event_type_sorts_by_score_then_last_time() -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    rows = [
        _snippet(id_=1, occurred_at=t0, event_type="LowScore", notable_score=5),
        _snippet(id_=2, occurred_at=t0 + timedelta(hours=1), event_type="HighScore", notable_score=20),
    ]
    groups = group_notable_rows_by_event_type(rows)
    assert len(groups) == 2
    assert groups[0].event_type == "HighScore"
    assert groups[1].event_type == "LowScore"


def test_group_notable_rows_by_event_type_message_from_latest_occurrence() -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    last_t = t0 + timedelta(days=1)
    rows = [
        _snippet(id_=1, occurred_at=t0, event_type="T", notable_score=10, message="old"),
        _snippet(id_=2, occurred_at=last_t, event_type="T", notable_score=10, message="newest"),
    ]
    groups = group_notable_rows_by_event_type(rows)
    assert len(groups) == 1
    assert groups[0].message == "newest"


def test_group_notable_rows_by_event_type_entity_none_when_mixed() -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    rows = [
        _snippet(id_=1, occurred_at=t0, event_type="T", notable_score=10, entity_name="a"),
        _snippet(id_=2, occurred_at=t0, event_type="T", notable_score=10, entity_name="b"),
    ]
    groups = group_notable_rows_by_event_type(rows)
    assert groups[0].entity_name is None


def test_group_notable_rows_by_event_type_empty() -> None:
    assert group_notable_rows_by_event_type([]) == []
