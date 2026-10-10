"""``SCREENSHOT_E2E_SEED`` 時のドキュメント用 DB シード。"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    DigestRecord,
    EventRecord,
    EventTypeGuide,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.dev.screenshot_e2e_seed import run_screenshot_e2e_seed_if_enabled
from vcenter_event_assistant.main import create_app


@pytest.mark.asyncio
async def test_screenshot_e2e_seed_inserts_rows_and_api_exposes_guide(
    monkeypatch: pytest.MonkeyPatch,
    open_client,
) -> None:
    monkeypatch.setenv("SCREENSHOT_E2E_SEED", "1")
    await run_screenshot_e2e_seed_if_enabled()

    async with session_scope() as session:
        n_vc = (await session.execute(select(func.count()).select_from(VCenter))).scalar_one()
        n_g = (await session.execute(select(func.count()).select_from(EventTypeGuide))).scalar_one()
        n_ev = (await session.execute(select(func.count()).select_from(EventRecord))).scalar_one()
        n_m = (await session.execute(select(func.count()).select_from(MetricSample))).scalar_one()
        n_d = (await session.execute(select(func.count()).select_from(DigestRecord))).scalar_one()
        n_rules = (await session.execute(select(func.count()).select_from(AlertRule))).scalar_one()
        n_hist = (await session.execute(select(func.count()).select_from(AlertHistory))).scalar_one()
    assert n_vc == 1
    assert n_g == 3
    assert n_ev == 1
    assert n_m >= 1
    assert n_d == 1
    assert n_rules == 1
    assert n_hist == 1

    app = create_app()
    async with open_client(app=app) as ac:
        resp = await ac.get("/api/events?limit=20")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    with_guide = [x for x in items if x.get("type_guide")]
    assert len(with_guide) >= 1
    assert with_guide[0]["type_guide"]["general_meaning"]


@pytest.mark.asyncio
async def test_screenshot_e2e_seed_skipped_without_env() -> None:
    await run_screenshot_e2e_seed_if_enabled()
    async with session_scope() as session:
        n_vc = (await session.execute(select(func.count()).select_from(VCenter))).scalar_one()
    assert n_vc == 0
