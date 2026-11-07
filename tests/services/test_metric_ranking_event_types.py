"""query_top_event_type_buckets の点数集計（Issue #301）。

イベント本文を全件読み込まずに、現行ルールで再計算した最大点数を返すこと。
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import EventRecord, EventScoreRule, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.rules.notable import final_notable_score
from vcenter_event_assistant.services.metric_ranking import query_top_event_type_buckets

T0 = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
_keys = itertools.count(1)

# (event_type, severity, message)。保存値はわざと 0 にして、保存値ではなく現行ルールで計算することを確かめる。
ROWS: list[tuple[str, str | None, str | None]] = [
    ("HostConnectionLostEvent", "info", "connection LOST to host"),
    ("HostConnectionLostEvent", "warning", "ok"),
    ("HostConnectionLostEvent", None, None),
    ("VmPoweredOnEvent", "INFO", "powered on"),
    ("VmPoweredOnEvent", "Error", "Task TIMEOUT"),
    ("VmPoweredOnEvent", "user", ""),
    ("CustomEvent", "warning", "disk Corrupt"),
    ("CustomEvent", "unknown", "fine"),
]


async def _seed(session: AsyncSession) -> None:
    vid = uuid.uuid4()
    session.add(VCenter(id=vid, name=f"vc-{vid.hex[:6]}", host="h", port=443, username="u", password="p"))
    session.add(EventScoreRule(event_type="CustomEvent", score_delta=7))
    await session.flush()
    for i, (et, sev, msg) in enumerate(ROWS):
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=T0 + timedelta(minutes=i),
                event_type=et,
                severity=sev,
                message=msg if msg is not None else "",
                vmware_key=next(_keys),
                notable_score=0,
            )
        )
    await session.flush()


def _expected() -> dict[str, int]:
    deltas = {"CustomEvent": 7}
    out: dict[str, int] = {}
    for et, sev, msg in ROWS:
        sc = final_notable_score(event_type=et, severity=sev, message=msg or "", score_delta=deltas.get(et, 0))
        out[et] = max(out.get(et, 0), sc)
    return out


@pytest.mark.asyncio
async def test_max_score_matches_per_row_recalculation() -> None:
    async with session_scope() as session:
        await _seed(session)
        got = await query_top_event_type_buckets(session, [EventRecord.occurred_at >= T0])
    assert {b.event_type: b.max_notable_score for b in got} == _expected()
    assert {b.event_type: b.event_count for b in got} == {
        "HostConnectionLostEvent": 3,
        "VmPoweredOnEvent": 3,
        "CustomEvent": 2,
    }


@pytest.mark.asyncio
async def test_event_messages_are_not_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """本文は判定にだけ使い、結果の列として受け取らない。"""
    statements: list[object] = []
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        statements.append(statement)
        return await original(self, statement, *args, **kwargs)

    async with session_scope() as session:
        await _seed(session)
        monkeypatch.setattr(AsyncSession, "execute", spy)
        await query_top_event_type_buckets(session, [EventRecord.occurred_at >= T0])
    column_sets = [
        {c.key for c in stmt.selected_columns}  # type: ignore[attr-defined]
        for stmt in statements
        if hasattr(stmt, "selected_columns")
    ]
    assert {"event_type", "severity", "has_keyword"} in column_sets
    assert all("message" not in cols for cols in column_sets)
