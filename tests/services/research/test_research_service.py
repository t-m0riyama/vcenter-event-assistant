"""research_service（検索 → 要約 → upsert キャッシュ）のテスト。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from vcenter_event_assistant.db.models import EventTypeResearch
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.research.research_service import (
    RESEARCH_STATUS_ERROR,
    RESEARCH_STATUS_NO_RESULT,
    RESEARCH_STATUS_OK,
    build_research_query,
    research_event_type,
    research_is_fresh,
)
from vcenter_event_assistant.services.research.search_provider import (
    SearchProvider,
    WebSearchResult,
)
from vcenter_event_assistant.settings import get_settings

_EVENT_TYPE = "esx.problem.scsi.device.io.latency.high"


class _FakeProvider(SearchProvider):
    name = "fake"

    def __init__(
        self,
        results: list[WebSearchResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._results = results or []
        self._error = error
        self.queries: list[str] = []

    async def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        return self._results[:max_results]


def _result() -> WebSearchResult:
    return WebSearchResult(
        title="KB 12345",
        url="https://knowledge.broadcom.com/external/article/12345",
        snippet="Check the storage path.",
    )


def test_build_research_query_contains_only_event_type() -> None:
    q = build_research_query(_EVENT_TYPE)
    assert _EVENT_TYPE in q
    # 固定テンプレート: event_type 以外の可変部を持たない
    assert q == build_research_query(_EVENT_TYPE)
    assert q.replace(_EVENT_TYPE, "{event_type}") == build_research_query(
        "other"
    ).replace("other", "{event_type}")


@pytest.mark.asyncio
async def test_research_saves_ok_row_with_sources_when_llm_unconfigured() -> None:
    """テスト環境は LLM_DIGEST_API_KEY 空 → 出典リンクのみの ok 行になる。"""
    provider = _FakeProvider(results=[_result()])
    async with session_scope() as session:
        row = await research_event_type(
            session, _EVENT_TYPE, settings=get_settings(), provider=provider
        )
        assert row.status == RESEARCH_STATUS_OK
        assert row.summary is None
        assert row.error_message == "digest LLM not configured"
        assert row.sources == [
            {
                "title": "KB 12345",
                "url": "https://knowledge.broadcom.com/external/article/12345",
            }
        ]
        assert row.origin == "auto"
        assert _EVENT_TYPE in row.query

    assert provider.queries == [build_research_query(_EVENT_TYPE)]


@pytest.mark.asyncio
async def test_research_saves_no_result_row_when_search_empty() -> None:
    async with session_scope() as session:
        row = await research_event_type(
            session, _EVENT_TYPE, settings=get_settings(), provider=_FakeProvider()
        )
        assert row.status == RESEARCH_STATUS_NO_RESULT
        assert row.summary is None
        assert row.sources is None


@pytest.mark.asyncio
async def test_research_saves_error_row_when_search_fails() -> None:
    provider = _FakeProvider(error=RuntimeError("rate limited"))
    async with session_scope() as session:
        row = await research_event_type(
            session, _EVENT_TYPE, settings=get_settings(), provider=provider
        )
        assert row.status == RESEARCH_STATUS_ERROR
        assert row.error_message == "rate limited"
        assert row.sources is None


@pytest.mark.asyncio
async def test_research_upserts_single_row_per_event_type() -> None:
    async with session_scope() as session:
        await research_event_type(
            session,
            _EVENT_TYPE,
            settings=get_settings(),
            provider=_FakeProvider(error=RuntimeError("boom")),
        )
    async with session_scope() as session:
        row = await research_event_type(
            session,
            _EVENT_TYPE,
            settings=get_settings(),
            provider=_FakeProvider(results=[_result()]),
        )
        assert row.status == RESEARCH_STATUS_OK
        assert row.error_message == "digest LLM not configured"

    async with session_scope() as session:
        count = (
            await session.execute(select(func.count()).select_from(EventTypeResearch))
        ).scalar_one()
        assert count == 1


def _patch_llm(monkeypatch: pytest.MonkeyPatch, response: str) -> None:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    monkeypatch.setattr(
        "vcenter_event_assistant.services.research.research_service.is_digest_llm_configured",
        lambda settings: True,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.research.research_service.build_chat_model",
        lambda settings, *, purpose: FakeListChatModel(responses=[response]),
    )


@pytest.mark.asyncio
async def test_research_saves_summary_when_llm_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_llm(monkeypatch, "- ストレージパスと HBA ファームウェアを確認する。")
    async with session_scope() as session:
        row = await research_event_type(
            session,
            _EVENT_TYPE,
            settings=get_settings(),
            provider=_FakeProvider(results=[_result()]),
        )
        assert row.status == RESEARCH_STATUS_OK
        assert row.summary == "- ストレージパスと HBA ファームウェアを確認する。"
        assert row.llm_model == get_settings().llm_digest_model
        assert row.error_message is None
        assert row.sources is not None


@pytest.mark.asyncio
async def test_research_no_useful_info_sentinel_becomes_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_llm(monkeypatch, "NO_USEFUL_INFO")
    async with session_scope() as session:
        row = await research_event_type(
            session,
            _EVENT_TYPE,
            settings=get_settings(),
            provider=_FakeProvider(results=[_result()]),
        )
        assert row.status == RESEARCH_STATUS_NO_RESULT
        assert row.summary is None
        # 出典は保持する（リンク集としては提示できる情報）
        assert row.sources is not None


def _row(status: str, searched_at: datetime) -> EventTypeResearch:
    return EventTypeResearch(
        event_type=_EVENT_TYPE,
        status=status,
        query="q",
        searched_at=searched_at,
    )


def test_research_is_fresh_ok_within_ttl() -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    fresh = _row(RESEARCH_STATUS_OK, now - timedelta(days=89))
    stale = _row(RESEARCH_STATUS_OK, now - timedelta(days=91))
    assert research_is_fresh(fresh, settings=settings, now=now)
    assert not research_is_fresh(stale, settings=settings, now=now)


def test_research_is_fresh_no_result_uses_shorter_ttl() -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    fresh = _row(RESEARCH_STATUS_NO_RESULT, now - timedelta(days=29))
    stale = _row(RESEARCH_STATUS_NO_RESULT, now - timedelta(days=31))
    assert research_is_fresh(fresh, settings=settings, now=now)
    assert not research_is_fresh(stale, settings=settings, now=now)


def test_research_is_fresh_error_rows_use_retry_window() -> None:
    """error 行は retry 間隔（既定 60 分）内は fresh、経過後に再調査対象へ戻る。"""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    recent = _row(RESEARCH_STATUS_ERROR, now - timedelta(minutes=59))
    old = _row(RESEARCH_STATUS_ERROR, now - timedelta(minutes=61))
    assert research_is_fresh(recent, settings=settings, now=now)
    assert not research_is_fresh(old, settings=settings, now=now)


def test_research_is_fresh_accepts_naive_searched_at() -> None:
    """SQLite 等で tz が落ちた searched_at も UTC とみなして判定する。"""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    row = _row(RESEARCH_STATUS_OK, now.replace(tzinfo=None))
    assert research_is_fresh(row, settings=settings, now=now)
