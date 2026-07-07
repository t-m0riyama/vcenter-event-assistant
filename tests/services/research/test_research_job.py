"""事前調査ジョブ（対象選定・サイクル実行）のテスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from vcenter_event_assistant.db.models import EventRecord, EventTypeResearch, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.research.research_job import (
    run_research_cycle,
    select_event_types_needing_research,
)
from vcenter_event_assistant.services.research.research_service import (
    RESEARCH_STATUS_ERROR,
    RESEARCH_STATUS_OK,
)
from vcenter_event_assistant.services.research.search_provider import (
    SearchProvider,
    WebSearchResult,
)
from vcenter_event_assistant.settings import Settings, get_settings


class _FakeProvider(SearchProvider):
    name = "fake"

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        self.queries.append(query)
        return [WebSearchResult(title="KB", url="https://example.com/kb", snippet="s")]


async def _seed_vcenter(session) -> uuid.UUID:
    vc = VCenter(
        name=f"vc-{uuid.uuid4().hex[:8]}", host="vc.example", username="u", password="p"
    )
    session.add(vc)
    await session.flush()
    return vc.id


def _event(
    vcenter_id: uuid.UUID, event_type: str, score: int, occurred_at: datetime, key: int
) -> EventRecord:
    return EventRecord(
        vcenter_id=vcenter_id,
        occurred_at=occurred_at,
        event_type=event_type,
        message="m",
        vmware_key=key,
        notable_score=score,
    )


def _job_settings(**overrides) -> Settings:
    base = {"database_url": "sqlite+aiosqlite:///:memory:"}
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_select_targets_filters_score_lookback_and_freshness() -> None:
    settings = _job_settings(
        research_event_score_threshold=40, research_event_lookback_hours=24
    )
    now = datetime.now(timezone.utc)
    recent = now - timedelta(hours=1)
    old = now - timedelta(hours=30)

    async with session_scope() as session:
        vid = await _seed_vcenter(session)
        session.add(_event(vid, "type.high", 80, recent, 1))
        session.add(_event(vid, "type.low-score", 10, recent, 2))
        session.add(_event(vid, "type.too-old", 90, old, 3))
        session.add(_event(vid, "type.fresh-research", 70, recent, 4))
        session.add(_event(vid, "type.stale-error", 60, recent, 5))
        session.add(
            EventTypeResearch(
                event_type="type.fresh-research",
                status=RESEARCH_STATUS_OK,
                query="q",
                searched_at=now - timedelta(days=1),
            )
        )
        session.add(
            EventTypeResearch(
                event_type="type.stale-error",
                status=RESEARCH_STATUS_ERROR,
                query="q",
                searched_at=now - timedelta(hours=2),
            )
        )
        await session.flush()

        targets = await select_event_types_needing_research(
            session, settings=settings, now=now
        )

    # スコア降順。低スコア・lookback 外・fresh なキャッシュ持ちは除外、
    # error 行は retry 間隔（60 分）経過後なので再調査対象
    assert targets == ["type.high", "type.stale-error"]


@pytest.mark.asyncio
async def test_select_targets_respects_max_per_cycle() -> None:
    settings = _job_settings(research_max_per_cycle=2)
    now = datetime.now(timezone.utc)

    async with session_scope() as session:
        vid = await _seed_vcenter(session)
        for i, score in enumerate((50, 90, 70), start=1):
            session.add(
                _event(vid, f"type.{score}", score, now - timedelta(hours=1), i)
            )
        await session.flush()

        targets = await select_event_types_needing_research(
            session, settings=settings, now=now
        )

    assert targets == ["type.90", "type.70"]


@pytest.mark.asyncio
async def test_run_research_cycle_noop_without_provider() -> None:
    """検索プロバイダ未構成（API キーなし）では 0 を返し何も書かない。"""
    researched = await run_research_cycle(get_settings())
    assert researched == 0
    async with session_scope() as session:
        rows = (await session.execute(select(EventTypeResearch))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_run_research_cycle_researches_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider()
    monkeypatch.setattr(
        "vcenter_event_assistant.services.research.research_job.build_search_provider",
        lambda settings: provider,
    )
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        vid = await _seed_vcenter(session)
        session.add(_event(vid, "type.a", 80, now - timedelta(hours=1), 1))
        session.add(_event(vid, "type.b", 60, now - timedelta(hours=1), 2))

    researched = await run_research_cycle(get_settings())
    assert researched == 2

    async with session_scope() as session:
        rows = (await session.execute(select(EventTypeResearch))).scalars().all()
        assert {r.event_type for r in rows} == {"type.a", "type.b"}
        assert all(r.status == RESEARCH_STATUS_OK for r in rows)

    # 2 回目のサイクルは全て fresh なので検索しない
    researched_again = await run_research_cycle(get_settings())
    assert researched_again == 0
    assert len(provider.queries) == 2
