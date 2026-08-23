"""``MOCK_MODE``: 外部 I/O なしでシード・収集・接続テスト・LLM・検索・通知が動くこと。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from vcenter_event_assistant.db.models import EventRecord, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.dev.mock_mode_seed import run_mock_mode_seed_if_enabled
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.services.ingestion import (
    ingest_events_for_vcenter,
    ingest_metrics_for_vcenter,
)
from vcenter_event_assistant.services.llm.llm_profile import (
    is_chat_llm_configured,
    is_digest_llm_configured,
)
from vcenter_event_assistant.services.research.search_provider import build_search_provider
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.settings_binding import bind_settings


def _enable_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_MODE", "1")
    get_settings.cache_clear()
    bind_settings(get_settings())


@pytest.mark.asyncio
async def test_mock_mode_seed_and_config_api(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_mock_mode(monkeypatch)
    await run_mock_mode_seed_if_enabled()

    async with session_scope() as session:
        n_vc = (await session.execute(select(func.count()).select_from(VCenter))).scalar_one()
        n_ev = (await session.execute(select(func.count()).select_from(EventRecord))).scalar_one()
        n_m = (await session.execute(select(func.count()).select_from(MetricSample))).scalar_one()
    assert n_vc == 1
    assert n_ev >= 3
    assert n_m >= 1

    # 冪等: 2 回目は増やさない
    await run_mock_mode_seed_if_enabled()
    async with session_scope() as session:
        n_vc2 = (await session.execute(select(func.count()).select_from(VCenter))).scalar_one()
    assert n_vc2 == 1

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        cfg = await ac.get("/api/config")
        assert cfg.status_code == 200
        body = cfg.json()
        assert body["mock_mode"] is True
        assert body["chat_web_search_available"] is True

        events = await ac.get("/api/events?limit=20")
        assert events.status_code == 200
        assert len(events.json()["items"]) >= 1

        vcs = await ac.get("/api/vcenters")
        assert vcs.status_code == 200
        vc_id = vcs.json()[0]["id"]

        with patch(
            "vcenter_event_assistant.collectors.connection.connect_vcenter",
            side_effect=AssertionError("connect_vcenter must not be called in MOCK_MODE"),
        ):
            test = await ac.get(f"/api/vcenters/{vc_id}/test")
        assert test.status_code == 200
        assert test.json()["ok"] is True
        assert "mock" in test.json()["product_name"].lower()


@pytest.mark.asyncio
async def test_mock_mode_ingestion_skips_pyvmomi(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_mock_mode(monkeypatch)
    await run_mock_mode_seed_if_enabled()
    settings = get_settings()

    async with session_scope(settings=settings) as session:
        vc = (
            await session.execute(select(VCenter).where(VCenter.name == "mock-demo-vc"))
        ).scalar_one()

        with (
            patch(
                "vcenter_event_assistant.services.ingestion.fetch_events_blocking",
                side_effect=AssertionError("real event fetch"),
            ),
            patch(
                "vcenter_event_assistant.services.ingestion.sample_hosts_blocking",
                side_effect=AssertionError("real metric sample"),
            ),
            patch(
                "vcenter_event_assistant.collectors.connection.connect_vcenter",
                side_effect=AssertionError("connect_vcenter"),
            ),
        ):
            n_ev = await ingest_events_for_vcenter(session, vc, settings=settings)
            n_m = await ingest_metrics_for_vcenter(session, vc, settings=settings)

    assert n_ev >= 1
    assert n_m >= 1


@pytest.mark.asyncio
async def test_mock_mode_chat_and_search_without_external_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_mock_mode(monkeypatch)
    settings = get_settings()
    assert is_chat_llm_configured(settings)
    assert is_digest_llm_configured(settings)
    provider = build_search_provider(settings)
    assert provider is not None
    assert provider.name == "mock"

    results = await provider.search("host disconnect", max_results=2)
    assert len(results) == 2
    assert results[0].url.startswith("https://example.com/")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch(
            "langchain_openai.ChatOpenAI",
            side_effect=AssertionError("ChatOpenAI must not be constructed"),
        ):
            r = await ac.post(
                "/api/chat",
                json={
                    "from": "2026-03-22T00:00:00Z",
                    "to": "2026-03-23T00:00:00Z",
                    "messages": [{"role": "user", "content": "質問"}],
                    "enable_web_search": True,
                },
            )
    assert r.status_code == 200
    data = r.json()
    assert data.get("error") in (None, "")
    assert "モック" in (data.get("assistant_content") or "")
    # WEB 検索ツール経路が動くと出典ブロックが付く
    assert "example.com/mock" in (data.get("assistant_content") or "")


@pytest.mark.asyncio
async def test_mock_mode_alert_notify_skips_smtp(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_mock_mode(monkeypatch)
    await run_mock_mode_seed_if_enabled()
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_email_to", "demo@example.com")

    with patch("smtplib.SMTP") as mock_smtp:
        evaluator = AlertEvaluator(settings)
        summary = await evaluator.evaluate_all()
        mock_smtp.assert_not_called()

    assert summary.rules_enabled >= 1
    assert evaluator.email_channel.__class__.__name__ == "LoggingEmailChannel"


@pytest.mark.asyncio
async def test_mock_mode_seed_skipped_when_disabled() -> None:
    await run_mock_mode_seed_if_enabled()
    async with session_scope() as session:
        n_vc = (await session.execute(select(func.count()).select_from(VCenter))).scalar_one()
    assert n_vc == 0


@pytest.mark.asyncio
async def test_mock_mode_digest_skips_copilot_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from vcenter_event_assistant.services.digest.digest_context import DigestContext
    from vcenter_event_assistant.services.digest.digest_llm import augment_digest_with_llm
    from vcenter_event_assistant.settings import Settings

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        mock_mode=True,
        llm_digest_provider="copilot_cli",
        llm_digest_api_key=None,
        scheduler_enabled=False,
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest.digest_llm.require_settings",
        lambda: s,
    )

    async def _boom(*_a: object, **_k: object) -> str:
        raise AssertionError("copilot CLI must not run in MOCK_MODE")

    monkeypatch.setattr(
        "vcenter_event_assistant.services.llm.copilot_cli_llm.run_copilot_cli_digest_completion",
        _boom,
    )

    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t0,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_event_groups=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    out, err = await augment_digest_with_llm(
        context=ctx,
        template_markdown="# テンプレ\n",
        settings=s,
    )
    assert err is None
    assert "モック" in out


@pytest.mark.asyncio
async def test_mock_mode_research_summary_skips_copilot_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vcenter_event_assistant.services.research.research_service import _summarize_results
    from vcenter_event_assistant.services.research.search_provider import WebSearchResult
    from vcenter_event_assistant.settings import Settings

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        mock_mode=True,
        llm_digest_provider="copilot_cli",
        llm_digest_api_key=None,
        scheduler_enabled=False,
    )

    async def _boom(*_a: object, **_k: object) -> str:
        raise AssertionError("copilot CLI must not run in MOCK_MODE")

    monkeypatch.setattr(
        "vcenter_event_assistant.services.research.research_service.run_copilot_cli_digest_completion",
        _boom,
    )

    summary, model, err = await _summarize_results(
        "vim.event.MockDemoHostConnectionLostEvent",
        [
            WebSearchResult(
                title="t",
                url="https://example.com/x",
                snippet="s",
            )
        ],
        s,
    )
    assert err is None
    assert summary is not None
    assert "モック" in summary
    assert model  # mock profile still exposes configured model id


def test_mock_mode_disables_langsmith_tracer() -> None:
    from vcenter_event_assistant.services.llm.llm_tracing import build_llm_runnable_config
    from vcenter_event_assistant.settings import Settings

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        mock_mode=True,
        langsmith_tracing_enabled=True,
        langsmith_api_key="ls-test",
        scheduler_enabled=False,
    )
    cfg = build_llm_runnable_config(s, run_kind="digest")
    assert "callbacks" not in cfg
