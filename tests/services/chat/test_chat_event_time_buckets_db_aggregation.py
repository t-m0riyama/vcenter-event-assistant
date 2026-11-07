"""build_chat_event_time_buckets を DB 側で集計したときの動作（Issue #301）。"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import EventRecord, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.chat.aggregation_limiter import AggregationLimitExceeded
from vcenter_event_assistant.services.chat.chat_event_time_buckets import build_chat_event_time_buckets

FROM = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
TO = FROM + timedelta(hours=2)
BUCKET = 15 * 60
_keys = itertools.count(1)


async def _add_vcenter(session: AsyncSession) -> uuid.UUID:
    vid = uuid.uuid4()
    session.add(VCenter(id=vid, name=f"vc-{vid.hex[:6]}", host="h", port=443, username="u", password="p"))
    await session.flush()
    return vid


def _event(vid: uuid.UUID, at: datetime, event_type: str, score: int | None = 0) -> EventRecord:
    return EventRecord(
        vcenter_id=vid,
        occurred_at=at,
        event_type=event_type,
        message="",
        vmware_key=next(_keys),
        notable_score=score,
    )


@pytest.mark.asyncio
async def test_boundary_sub_second_and_to_exclusion() -> None:
    async with session_scope() as session:
        vid = await _add_vcenter(session)
        session.add_all(
            [
                _event(vid, FROM + timedelta(minutes=14, seconds=59, microseconds=999_600), "A", 10),
                _event(vid, FROM + timedelta(minutes=15), "A", 30),
                _event(vid, FROM + timedelta(minutes=15, seconds=1), "B", None),
                _event(vid, TO, "A", 99),
            ]
        )
        await session.flush()
        out = await build_chat_event_time_buckets(session, FROM, TO, vcenter_id=None, bucket_sec=BUCKET)
    assert [b.bucket_start_utc for b in out.buckets] == [FROM, FROM + timedelta(minutes=15)]
    assert out.buckets[0].by_type == {"A": 1}
    assert out.buckets[1].total == 2
    assert out.buckets[1].by_type == {"A": 1, "B": 1}
    top = {a.event_type: a.max_notable_score for a in out.buckets[1].alert_top_types}
    assert top == {"A": 30, "B": 0}


@pytest.mark.asyncio
async def test_sub_second_from_is_truncated_to_the_second() -> None:
    """ms 付きの from でも、境界ちょうどのイベントは次のバケットに入る。"""
    async with session_scope() as session:
        vid = await _add_vcenter(session)
        session.add(_event(vid, FROM + timedelta(minutes=15), "A"))
        await session.flush()
        out = await build_chat_event_time_buckets(
            session, FROM + timedelta(milliseconds=500), TO, vcenter_id=None, bucket_sec=BUCKET
        )
    assert out.from_utc == FROM
    assert [b.bucket_start_utc for b in out.buckets] == [FROM + timedelta(minutes=15)]


@pytest.mark.asyncio
async def test_row_limit_raises_when_exceeded_and_allows_exact() -> None:
    """集計後の行数（バケット × 種別）が上限を超えたら打ち切る。ちょうどなら通す。"""
    async with session_scope() as session:
        vid = await _add_vcenter(session)
        for et in ("A", "B", "C"):
            session.add(_event(vid, FROM + timedelta(minutes=1), et))
        await session.flush()
        ok = await build_chat_event_time_buckets(
            session, FROM, TO, vcenter_id=None, bucket_sec=BUCKET, max_rows=3
        )
        assert ok.buckets[0].total == 3
        with pytest.raises(AggregationLimitExceeded):
            await build_chat_event_time_buckets(
                session, FROM, TO, vcenter_id=None, bucket_sec=BUCKET, max_rows=2
            )


@pytest.mark.asyncio
async def test_query_groups_in_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """イベントを 1 行ずつ読まず、バケット × 種別の集計済みの列だけを受け取る。"""
    statements: list[object] = []
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        statements.append(statement)
        return await original(self, statement, *args, **kwargs)

    async with session_scope() as session:
        vid = await _add_vcenter(session)
        for m in range(0, 60, 5):
            session.add(_event(vid, FROM + timedelta(minutes=m), "A"))
        await session.flush()
        monkeypatch.setattr(AsyncSession, "execute", spy)
        out = await build_chat_event_time_buckets(session, FROM, TO, vcenter_id=None, bucket_sec=BUCKET)
    assert sum(b.total for b in out.buckets) == 12
    assert len(statements) == 1
    columns = {c.key for c in statements[0].selected_columns}  # type: ignore[attr-defined]
    assert columns == {"bidx", "event_type", "cnt", "max_score"}
