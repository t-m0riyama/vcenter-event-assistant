"""調査結果の付記ブロック生成と日次ダイジェストへの連結のテスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from vcenter_event_assistant.db.models import EventRecord, EventTypeResearch, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.digest.digest_run import run_digest_once
from vcenter_event_assistant.services.research.research_attach import (
    RESEARCH_SECTION_HEADING,
    ResearchAttachmentItem,
    build_research_attachment_markdown,
    render_research_attachment,
    select_research_for_window,
)
from vcenter_event_assistant.services.research.research_service import (
    RESEARCH_DISCLAIMER,
    RESEARCH_STATUS_ERROR,
    RESEARCH_STATUS_NO_RESULT,
    RESEARCH_STATUS_OK,
)
from vcenter_event_assistant.settings import Settings, get_settings

_NOW = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
_FROM = _NOW - timedelta(days=1)


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


def _research(
    event_type: str, status: str, summary: str | None = None
) -> EventTypeResearch:
    return EventTypeResearch(
        event_type=event_type,
        status=status,
        query="q",
        summary=summary,
        sources=[{"title": "KB 1", "url": "https://example.com/kb1"}],
        searched_at=_NOW - timedelta(hours=1),
    )


def _attach_settings(**overrides) -> Settings:
    base = {"database_url": "sqlite+aiosqlite:///:memory:"}
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_select_research_only_ok_rows_ordered_by_score() -> None:
    settings = _attach_settings(research_attach_max_items=2)
    inside = _NOW - timedelta(hours=2)

    async with session_scope() as session:
        vid = await _seed_vcenter(session)
        session.add(_event(vid, "type.top", 90, inside, 1))
        session.add(_event(vid, "type.second", 70, inside, 2))
        session.add(_event(vid, "type.third", 60, inside, 3))
        session.add(_event(vid, "type.no-result", 80, inside, 4))
        session.add(_event(vid, "type.error", 75, inside, 5))
        session.add(_research("type.top", RESEARCH_STATUS_OK, "- 原因 A"))
        session.add(_research("type.second", RESEARCH_STATUS_OK, "- 原因 B"))
        session.add(_research("type.third", RESEARCH_STATUS_OK, "- 原因 C"))
        session.add(_research("type.no-result", RESEARCH_STATUS_NO_RESULT))
        session.add(_research("type.error", RESEARCH_STATUS_ERROR))
        await session.flush()

        items = await select_research_for_window(
            session, from_utc=_FROM, to_utc=_NOW, settings=settings
        )

    # no_result / error は除外。スコア順で上限 2 件
    assert [i.event_type for i in items] == ["type.top", "type.second"]
    assert items[0].max_score == 90


@pytest.mark.asyncio
async def test_select_research_empty_without_high_score_events() -> None:
    async with session_scope() as session:
        items = await select_research_for_window(
            session, from_utc=_FROM, to_utc=_NOW, settings=get_settings()
        )
    assert items == []


def test_render_research_attachment_includes_disclaimer_and_sources() -> None:
    md = render_research_attachment(
        [
            ResearchAttachmentItem(
                event_type="esx.problem.scsi.device.io.latency.high",
                max_score=80,
                summary="- ストレージパスを確認する。",
                sources=[{"title": "KB 1", "url": "https://example.com/kb1"}],
                searched_at=_NOW,
            )
        ]
    )
    assert md is not None
    assert md.startswith(RESEARCH_SECTION_HEADING)
    assert RESEARCH_DISCLAIMER in md
    assert (
        "esx.problem.scsi.device.io.latency.high（最大スコア 80 / 調査日 2026-07-08）"
        in md
    )
    assert "- ストレージパスを確認する。" in md
    assert "- [KB 1](https://example.com/kb1)" in md


def test_render_research_attachment_without_summary_shows_sources_only() -> None:
    """LLM 未設定で summary None の行はリンク集として付記する。"""
    md = render_research_attachment(
        [
            ResearchAttachmentItem(
                event_type="type.a",
                max_score=50,
                summary=None,
                sources=[{"title": "KB 1", "url": "https://example.com/kb1"}],
                searched_at=_NOW,
            )
        ]
    )
    assert md is not None
    assert "出典:" in md


def test_render_research_attachment_none_when_empty() -> None:
    assert render_research_attachment([]) is None


@pytest.mark.asyncio
async def test_daily_digest_appends_research_section() -> None:
    inside = _NOW - timedelta(hours=2)
    async with session_scope() as session:
        vid = await _seed_vcenter(session)
        session.add(_event(vid, "type.top", 90, inside, 1))
        session.add(_research("type.top", RESEARCH_STATUS_OK, "- 原因 A"))

    async with session_scope() as session:
        row = await run_digest_once(
            session,
            kind="daily",
            from_utc=_FROM,
            to_utc=_NOW,
            settings=get_settings(),
        )
        assert RESEARCH_SECTION_HEADING in row.body_markdown
        assert RESEARCH_DISCLAIMER in row.body_markdown
        # 付記は本文末尾（LLM 追記より後）に連結される
        assert row.body_markdown.rstrip().endswith("- [KB 1](https://example.com/kb1)")


@pytest.mark.asyncio
async def test_weekly_digest_does_not_append_research_section() -> None:
    inside = _NOW - timedelta(hours=2)
    async with session_scope() as session:
        vid = await _seed_vcenter(session)
        session.add(_event(vid, "type.top", 90, inside, 1))
        session.add(_research("type.top", RESEARCH_STATUS_OK, "- 原因 A"))

    async with session_scope() as session:
        row = await run_digest_once(
            session,
            kind="weekly",
            from_utc=_FROM,
            to_utc=_NOW,
            settings=get_settings(),
        )
        assert RESEARCH_SECTION_HEADING not in row.body_markdown


@pytest.mark.asyncio
async def test_daily_digest_without_research_cache_unchanged() -> None:
    async with session_scope() as session:
        row = await run_digest_once(
            session,
            kind="daily",
            from_utc=_FROM,
            to_utc=_NOW,
            settings=get_settings(),
        )
        assert RESEARCH_SECTION_HEADING not in row.body_markdown


@pytest.mark.asyncio
async def test_build_research_attachment_markdown_roundtrip() -> None:
    inside = _NOW - timedelta(hours=2)
    async with session_scope() as session:
        vid = await _seed_vcenter(session)
        session.add(_event(vid, "type.top", 90, inside, 1))
        session.add(_research("type.top", RESEARCH_STATUS_OK, "- 原因 A"))
        await session.flush()

        md = await build_research_attachment_markdown(
            session, from_utc=_FROM, to_utc=_NOW, settings=get_settings()
        )
    assert md is not None
    assert "type.top" in md
