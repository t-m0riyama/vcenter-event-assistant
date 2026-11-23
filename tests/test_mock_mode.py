"""``MOCK_MODE``: 外部 I/O なしでシード・収集・接続テスト・LLM・検索・通知が動くこと。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select

from vcenter_event_assistant.api.schemas.incident_timeline_view import IncidentTimelineViewRequest
from vcenter_event_assistant.db.models import EventRecord, MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.dev.mock_mode_seed import run_mock_mode_seed_if_enabled
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.services.incident_timeline_view import build_incident_timeline_view
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
async def test_mock_mode_seed_and_config_api(monkeypatch: pytest.MonkeyPatch, open_client) -> None:
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
    async with open_client(app=app) as ac:
        cfg = await ac.get("/api/config")
        assert cfg.status_code == 200
        body = cfg.json()
        assert body["mock_mode"] is True
        assert body["chat_web_search_available"] is True

        events = await ac.get("/api/events?limit=20")
        assert events.status_code == 200
        assert len(events.json()["items"]) >= 1
        now = datetime.now(timezone.utc)
        view = await ac.post("/api/incident-timeline/view", json={
            "from": (now - timedelta(hours=1)).isoformat(),
            "to": now.isoformat(),
            "sources": ["event"],
        })
        assert view.status_code == 200
        timeline = view.json()
        [pattern] = timeline["highlights"]["detected_patterns"]
        assert (pattern["pattern_id"], pattern["event_count"]) == ("host-conn-flapping", 3)
        disconnects = [e for e in timeline["items"] if e["ref"]["event_type"] == "vim.event.HostConnectionLostEvent"]
        assert sum(e["count"] for e in disconnects) == 3
        assert {e["score"] for e in disconnects} == {40}

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

        vm_moids = (await session.scalars(
            select(EventRecord.entity_moid).where(
                EventRecord.vcenter_id == vc.id,
                EventRecord.entity_type == "VirtualMachine",
            )
        )).all()
        assert len(vm_moids) == 3
        assert set(vm_moids) == {"vm-mock-01"}
        now = datetime.now(timezone.utc)
        view = await build_incident_timeline_view(
            session,
            IncidentTimelineViewRequest(
                from_time=now - timedelta(hours=1), to_time=now, vcenter_id=vc.id, sources=["event"],
            ),
            owner_key="mock-ingestion-test",
        )
        [pattern] = view.highlights.detected_patterns
        assert (pattern.pattern_id, pattern.event_count) == ("host-conn-flapping", 6)

    assert n_ev >= 1
    assert n_m >= 1


@pytest.mark.asyncio
async def test_mock_mode_chat_and_search_without_external_keys(
    monkeypatch: pytest.MonkeyPatch,
    open_client,
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
    async with open_client(app=app) as ac:
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


async def test_mock_tasks_are_saved_once_and_visible_in_events_and_timeline(
    monkeypatch: pytest.MonkeyPatch, open_client, no_external_collectors: None
) -> None:
    from vcenter_event_assistant.mocks import mock_collectors
    from vcenter_event_assistant.plugins.registry import build_collector_registry
    from vcenter_event_assistant.plugins.runtime import run_collector_for_vcenter

    _enable_mock_mode(monkeypatch)
    await run_mock_mode_seed_if_enabled()
    settings = get_settings()
    async with session_scope() as session:
        vc_id = (await session.scalars(select(VCenter.id))).one()

    now = datetime.now(timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(mock_collectors, "datetime", FrozenDateTime)
    registration = build_collector_registry(settings).get("builtin.vcenter.tasks")
    assert registration is not None
    for _ in range(2):
        result = await run_collector_for_vcenter(settings, registration, vc_id)
        assert result.status == "ok"

    async with open_client(app=create_app()) as ac:
        events = await ac.get("/api/events", params={"event_type_contains": "task."})
        assert events.status_code == 200
        assert sorted(event["event_type"] for event in events.json()["items"]) == [
            "task.canceled.VirtualMachine.migrate",
            "task.error.VirtualMachine.powerOn",
            "task.success.VirtualMachine.powerOn",
        ]

        timeline = await ac.post(
            "/api/incident-timeline/view",
            json={
                "from": (now - timedelta(hours=1)).isoformat(),
                "to": now.isoformat(),
                "sources": ["event"],
            },
        )
        assert timeline.status_code == 200
        task_scores = {
            item["ref"]["event_type"]: item["score"]
            for item in timeline.json()["items"]
            if item["ref"]["event_type"].startswith("task.")
        }
        assert task_scores == {
            "task.canceled.VirtualMachine.migrate": 20,
            "task.error.VirtualMachine.powerOn": 50,
        }


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
        from vcenter_event_assistant.services.alerting.notification_outbox import deliver_notifications
        await deliver_notifications(settings)
        mock_smtp.assert_not_called()

    assert summary.rules_enabled >= 1
    async with session_scope() as session:
        from vcenter_event_assistant.db.models import AlertHistory
        rows = (await session.scalars(select(AlertHistory))).all()
        assert rows and all(row.channel == 'mock' and row.delivery_status == 'succeeded' for row in rows)
        assert any(row.context_key == "vim.event.HostConnectionLostEvent" for row in rows)
        [pattern] = [row for row in rows if row.context_key.endswith(":host-conn-flapping")]
        assert pattern.state == "firing"


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


@pytest.mark.asyncio
async def test_inventory_mock_seed_and_job_share_topology(monkeypatch) -> None:
    from vcenter_event_assistant.db.models import (
        InventoryObject,
        InventoryRelation,
        InventorySyncRun,
        InventorySyncState,
    )
    from vcenter_event_assistant.mocks.mock_collectors import (
        MOCK_HOST_MOID,
        MOCK_VM_MOID,
    )
    from vcenter_event_assistant.mocks.mock_inventory import mock_inventory
    from vcenter_event_assistant.services import inventory

    _enable_mock_mode(monkeypatch)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        "vcenter_event_assistant.dev.mock_mode_seed.datetime",
        type("FrozenDateTime", (datetime,), {"now": staticmethod(lambda _: now)}),
    )
    await run_mock_mode_seed_if_enabled()
    async with session_scope() as session:
        # この変更より前にシードした DB を再現する。
        for model in (
            InventorySyncState,
            InventorySyncRun,
            InventoryRelation,
            InventoryObject,
        ):
            await session.execute(delete(model))
    await run_mock_mode_seed_if_enabled()

    def unexpected(*args):
        pytest.fail("モックで vCenter に接続した")

    monkeypatch.setattr(inventory, "read_vcenter_inventory", unexpected)
    async with session_scope() as session:
        vc = (await session.scalars(select(VCenter))).one()
        state = await session.get(InventorySyncState, vc.id)
        seed = mock_inventory(now)
        assert state.instance_uuid == seed.instance_uuid
        assert state.object_count == 10
        objects = {
            item.moid: item.name
            for item in await session.scalars(select(InventoryObject))
        }
        assert objects[MOCK_HOST_MOID] == "esxi-mock-01"
        assert objects[MOCK_VM_MOID] == "vm-mock-web-01"
        assert objects["datastore-mock-01"] == "mock-datastore"
        rows = (await session.scalars(select(InventoryRelation))).all()
        closed = [r for r in rows if r.valid_to is not None]
        assert len(closed) == 1 and closed[0].kind == "vm_host"
        assert closed[0].child_moid == MOCK_VM_MOID
        assert state.first_success_at == closed[0].valid_from
        oldest_event = await session.scalar(select(func.min(EventRecord.occurred_at)))
        oldest_metric = await session.scalar(select(func.min(MetricSample.sampled_at)))
        assert state.first_success_at < oldest_event
        assert state.first_success_at < oldest_metric
        assert await session.scalar(select(InventorySyncRun.id).limit(1)) is not None
        assert {
            (r.kind, r.child_moid, r.parent_moid) for r in rows if r.valid_to is None
        } == seed.relations

    monkeypatch.setattr(inventory, "utcnow", lambda: now + timedelta(minutes=30))
    await inventory.sync_inventory(get_settings())
    async with session_scope() as session:
        rows = (await session.scalars(select(InventoryRelation))).all()
        assert len([r for r in rows if r.valid_to is not None]) == 2
        moved = mock_inventory(now + timedelta(minutes=30))
        assert {
            (r.kind, r.child_moid, r.parent_moid) for r in rows if r.valid_to is None
        } == moved.relations
