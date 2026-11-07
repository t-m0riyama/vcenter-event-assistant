"""インシデントタイムライン等の集計の上限（Issue #301）。

- 同じ秒の中の from/to は 400（500 にしない）
- イベントの集計行が上限を超えたら 422
- 同時実行数の上限（利用者ごと・全体）を超えたら待たずに 503
- ``/api/incident-timeline`` にもレート制限がかかる
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from vcenter_event_assistant.db.models import EventRecord, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.main import _rate_limit_spec, create_app
from vcenter_event_assistant.rate_limit import _rate_limiter
from vcenter_event_assistant.services.chat import chat_context_payloads
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.settings_binding import require_settings

FROM = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)


def _body(**overrides: object) -> dict:
    base: dict[str, object] = {"from": "2026-03-22T00:00:00Z", "to": "2026-03-22T02:00:00Z"}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_from_and_to_in_the_same_second_is_400(client: AsyncClient) -> None:
    r = await client.post(
        "/api/incident-timeline",
        json=_body(**{"from": "2026-03-22T00:00:00.100Z", "to": "2026-03-22T00:00:00.900Z"}),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_too_many_aggregated_event_rows_is_422(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    vid = uuid.uuid4()
    async with session_scope() as session:
        session.add(VCenter(id=vid, name="vc-limit", host="h", port=443, username="u", password="p"))
        await session.flush()
        for i, et in enumerate(("A", "B", "C")):
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=FROM + timedelta(minutes=1),
                    event_type=et,
                    message="",
                    vmware_key=10_000 + i,
                )
            )
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 2)
    r = await client.post("/api/incident-timeline", json=_body(include_period_metrics_cpu=True))
    assert r.status_code == 422
    assert "vCenter を指定" in r.json()["detail"]

    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 3)
    r = await client.post("/api/incident-timeline", json=_body(include_period_metrics_cpu=True))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_concurrent_requests_are_limited_per_user_and_released(
    open_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """メトリクスのトグルがなくても上限の対象になる。同じ利用者の 2 本目は 503、別の利用者は通る。"""
    monkeypatch.setattr(require_settings(), "context_aggregation_concurrency", 4)
    monkeypatch.setattr(require_settings(), "context_aggregation_concurrency_per_user", 1)
    started = asyncio.Event()
    release = asyncio.Event()
    original = chat_context_payloads.build_digest_context
    calls = 0

    async def slow_digest(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(chat_context_payloads, "build_digest_context", slow_digest)

    async with open_client("admin") as admin, open_client("viewer") as viewer:
        first = asyncio.create_task(admin.post("/api/incident-timeline", json=_body()))
        await asyncio.wait_for(started.wait(), timeout=10)

        busy = await admin.post("/api/incident-timeline", json=_body())
        assert busy.status_code == 503
        assert busy.headers.get("retry-after")

        other_user = await viewer.post("/api/incident-timeline", json=_body())
        assert other_user.status_code == 200

        release.set()
        assert (await first).status_code == 200

        again = await admin.post("/api/incident-timeline", json=_body())
        assert again.status_code == 200


@pytest.mark.asyncio
async def test_global_concurrency_limit_rejects_other_users(
    open_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(require_settings(), "context_aggregation_concurrency", 1)
    started = asyncio.Event()
    release = asyncio.Event()
    original = chat_context_payloads.build_digest_context
    calls = 0

    async def slow_digest(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(chat_context_payloads, "build_digest_context", slow_digest)

    async with open_client("admin") as admin, open_client("viewer") as viewer:
        first = asyncio.create_task(admin.post("/api/incident-timeline", json=_body()))
        await asyncio.wait_for(started.wait(), timeout=10)
        assert (await viewer.post("/api/incident-timeline", json=_body())).status_code == 503
        release.set()
        assert (await first).status_code == 200


@pytest.mark.asyncio
async def test_slot_is_released_when_aggregation_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(require_settings(), "context_aggregation_concurrency", 1)

    async def broken_digest(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(chat_context_payloads, "build_digest_context", broken_digest)
    with pytest.raises(RuntimeError):
        await client.post("/api/incident-timeline", json=_body())
    monkeypatch.undo()
    r = await client.post("/api/incident-timeline", json=_body())
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_slot_is_released_when_request_is_cancelled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """集計の途中で要求が取り消されても（CancelledError）、枠は返る。"""
    monkeypatch.setattr(require_settings(), "context_aggregation_concurrency", 1)
    started = asyncio.Event()
    original = chat_context_payloads.build_digest_context

    async def hanging_digest(*args, **kwargs):  # type: ignore[no-untyped-def]
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(chat_context_payloads, "build_digest_context", hanging_digest)
    task = asyncio.create_task(client.post("/api/incident-timeline", json=_body()))
    await asyncio.wait_for(started.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    monkeypatch.setattr(chat_context_payloads, "build_digest_context", original)
    r = await client.post("/api/incident-timeline", json=_body())
    assert r.status_code == 200


def test_incident_timeline_is_rate_limited_path() -> None:
    assert _rate_limit_spec("POST", "/api/incident-timeline") == ("incident_timeline", 60)
    assert _rate_limit_spec("GET", "/api/incident-timeline/snapshots/manual") is None


async def test_incident_timeline_returns_429_over_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """上限値の辞書に登録漏れがあると、本番だけ KeyError で 500 になる。ミドルウェアを通して確かめる。"""
    monkeypatch.delenv("VEA_PYTEST")
    monkeypatch.setenv("RATE_LIMIT_CHAT_PER_MINUTE", "1")  # タイムラインはその 2 倍
    get_settings.cache_clear()
    _rate_limiter._hits.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as ac:
            codes = [
                (
                    await ac.post(
                        "/api/incident-timeline",
                        json=_body(),
                        headers={"X-Requested-With": "XMLHttpRequest"},
                    )
                ).status_code
                for _ in range(3)
            ]
    finally:
        _rate_limiter._hits.clear()
        get_settings.cache_clear()
    assert 429 not in codes[:2]
    assert 500 not in codes
    assert codes[2] == 429
