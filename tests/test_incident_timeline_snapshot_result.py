"""手動スナップショットに view の結果を保存する機能（POST /snapshots/manual の view_request）のテスト。"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from vcenter_event_assistant.db.models import EventRecord, IncidentTimelineManualSnapshot, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.chat.aggregation_limiter import aggregation_slot
from vcenter_event_assistant.settings_binding import require_settings

T0 = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
URL = "/api/incident-timeline/snapshots/manual"
_keys = itertools.count(1)


def _view_request(**overrides: object) -> dict:
    base: dict[str, object] = {"from": "2026-03-22T00:00:00Z", "to": "2026-03-22T02:00:00Z"}
    base.update(overrides)
    return base


def _body(**overrides: object) -> dict:
    base: dict[str, object] = {
        "from": "2026-03-22T00:00:00Z",
        "to": "2026-03-22T02:00:00Z",
        "timestamp_utc": "2026-03-22T03:00:00Z",
        "operator_note": "保存時点の結果を残す",
    }
    base.update(overrides)
    return base


async def _seed_events(count: int = 2) -> uuid.UUID:
    vid = uuid.uuid4()
    async with session_scope() as session:
        session.add(VCenter(id=vid, name=f"vc-{vid}", host="h", port=443, username="u", password="p"))
        for i in range(count):
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=T0 + timedelta(minutes=10 * (i + 1)),
                    event_type=f"Type{i}",
                    message=f"message {i}",
                    entity_name=f"host-{i}",
                    entity_type="HostSystem",
                    notable_score=50,
                    vmware_key=next(_keys),
                )
            )
    return vid


async def _snapshot_count() -> int:
    async with session_scope() as session:
        return int((await session.execute(select(func.count()).select_from(IncidentTimelineManualSnapshot))).scalar_one())


async def _insert_row(**extra: object) -> uuid.UUID:
    sid = uuid.uuid4()
    async with session_scope() as session:
        session.add(
            IncidentTimelineManualSnapshot(
                id=sid,
                from_time=T0,
                to_time=T0 + timedelta(hours=2),
                timestamp_utc=T0 + timedelta(hours=3),
                operator_note="row",
                build_request_payload={"from": "2026-03-22T00:00:00Z", "to": "2026-03-22T02:00:00Z"},
                **extra,
            )
        )
    return sid


@pytest.mark.asyncio
async def test_save_with_view_request_runs_view_and_stores_request_and_result(client: AsyncClient) -> None:
    vid = await _seed_events()
    r = await client.post(URL, json=_body(view_request=_view_request(vcenter_id=str(vid), min_score=10)))
    assert r.status_code == 201, r.text
    snapshot_id = r.json()["snapshot_id"]
    # 作成レスポンスは大きい結果を載せない
    assert "result" not in r.json()

    async with session_scope() as session:
        row = await session.get(IncidentTimelineManualSnapshot, uuid.UUID(snapshot_id))
        assert row is not None
        assert row.view_request_payload is not None
        assert row.view_request_payload["vcenter_id"] == str(vid)
        assert row.view_request_payload["min_score"] == 10
        assert row.result_payload is not None
        assert row.result_payload["total_items"] == 2
        assert len(row.result_payload["items"]) == 2

    detail = (await client.get(f"{URL}/{snapshot_id}")).json()
    assert detail["has_result"] is True
    assert detail["result"]["total_items"] == 2
    assert detail["view_request"]["vcenter_id"] == str(vid)
    assert detail["operator_note"] == "保存時点の結果を残す"


@pytest.mark.asyncio
async def test_saved_result_is_not_recomputed_when_data_changes(client: AsyncClient) -> None:
    await _seed_events(2)
    snapshot_id = (await client.post(URL, json=_body(view_request=_view_request()))).json()["snapshot_id"]
    await _seed_events(3)
    detail = (await client.get(f"{URL}/{snapshot_id}")).json()
    assert detail["result"]["total_items"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["result", "result_payload", "view_result"])
async def test_client_cannot_send_result(client: AsyncClient, field: str) -> None:
    r = await client.post(URL, json=_body(view_request=_view_request(), **{field: {"items": []}}))
    assert r.status_code == 422
    assert await _snapshot_count() == 0


@pytest.mark.asyncio
async def test_view_request_range_wins_over_top_level_range(client: AsyncClient) -> None:
    r = await client.post(
        URL,
        json=_body(
            view_request=_view_request(**{"from": "2026-03-22T00:30:00Z", "to": "2026-03-22T01:30:00Z"}),
        ),
    )
    assert r.status_code == 201
    detail = (await client.get(f"{URL}/{r.json()['snapshot_id']}")).json()
    assert detail["from"] == "2026-03-22T00:30:00Z"
    assert detail["to"] == "2026-03-22T01:30:00Z"
    assert detail["result"]["from_utc"].startswith("2026-03-22T00:30:00")


@pytest.mark.asyncio
async def test_busy_view_returns_503_and_saves_nothing(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(require_settings(), "context_aggregation_concurrency", 1)
    with aggregation_slot("someone-else", global_limit=1, per_owner_limit=1):
        r = await client.post(URL, json=_body(view_request=_view_request()))
    assert r.status_code == 503
    assert r.headers.get("retry-after")
    assert await _snapshot_count() == 0


@pytest.mark.asyncio
async def test_too_many_rows_returns_422_and_saves_nothing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_events(3)
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 2)
    r = await client.post(URL, json=_body(view_request=_view_request()))
    assert r.status_code == 422
    assert await _snapshot_count() == 0


@pytest.mark.asyncio
async def test_invalid_view_request_is_422(client: AsyncClient) -> None:
    r = await client.post(URL, json=_body(view_request=_view_request(min_score=1000)))
    assert r.status_code == 422
    assert await _snapshot_count() == 0


@pytest.mark.asyncio
async def test_legacy_request_without_view_request_still_works(client: AsyncClient) -> None:
    r = await client.post(URL, json=_body())
    assert r.status_code == 201
    async with session_scope() as session:
        row = await session.get(IncidentTimelineManualSnapshot, uuid.UUID(r.json()["snapshot_id"]))
        assert row is not None
        assert row.result_payload is None
        assert row.view_request_payload is None
    detail = (await client.get(f"{URL}/{r.json()['snapshot_id']}")).json()
    assert detail["has_result"] is False
    assert detail["result"] is None
    assert detail["view_request"] is None


@pytest.mark.asyncio
async def test_list_has_no_result_but_has_flag_and_view_request(client: AsyncClient) -> None:
    await _seed_events()
    with_result = (await client.post(URL, json=_body(view_request=_view_request()))).json()["snapshot_id"]
    legacy = (await client.post(URL, json=_body(timestamp_utc="2026-03-22T04:00:00Z"))).json()["snapshot_id"]

    data = (await client.get(URL)).json()
    by_id = {item["snapshot_id"]: item for item in data["items"]}
    assert all("result" not in item and "result_payload" not in item for item in data["items"])
    assert by_id[with_result]["has_result"] is True
    assert by_id[with_result]["view_request"]["min_score"] == 1
    assert by_id[legacy]["has_result"] is False
    assert by_id[legacy]["view_request"] is None


@pytest.mark.asyncio
async def test_detail_404(client: AsyncClient) -> None:
    assert (await client.get(f"{URL}/{uuid.uuid4()}")).status_code == 404
    assert (await client.get(f"{URL}/not-a-uuid")).status_code == 404


@pytest.mark.asyncio
async def test_old_row_with_null_result_loads(client: AsyncClient) -> None:
    sid = await _insert_row()
    detail = (await client.get(f"{URL}/{sid}")).json()
    assert detail["has_result"] is False
    assert detail["result"] is None
    assert detail["from"] == "2026-03-22T00:00:00Z"
    listed = (await client.get(URL)).json()["items"]
    assert listed[0]["has_result"] is False


@pytest.mark.asyncio
async def test_result_that_no_longer_matches_the_schema_is_treated_as_no_result(client: AsyncClient) -> None:
    sid = await _insert_row(
        result_payload={"from_utc": "2026-03-22T00:00:00Z", "legacy_field": 1},
        view_request_payload={"from": "2026-03-22T00:00:00Z", "to": "2026-03-22T02:00:00Z"},
    )
    r = await client.get(f"{URL}/{sid}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["has_result"] is False
    assert detail["result"] is None
    assert detail["view_request"]["from"] == "2026-03-22T00:00:00Z"


@pytest.mark.asyncio
async def test_unreadable_view_request_does_not_break_detail(client: AsyncClient) -> None:
    sid = await _insert_row(view_request_payload={"unknown": True})
    r = await client.get(f"{URL}/{sid}")
    assert r.status_code == 200
    assert r.json()["view_request"] is None
    assert (await client.get(URL)).status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_save_but_can_read_detail(
    viewer_client: AsyncClient, operator_client: AsyncClient
) -> None:
    r = await viewer_client.post(URL, json=_body(view_request=_view_request()))
    assert r.status_code == 403
    assert await _snapshot_count() == 0

    created = await operator_client.post(URL, json=_body(view_request=_view_request()))
    assert created.status_code == 201
    r = await viewer_client.get(f"{URL}/{created.json()['snapshot_id']}")
    assert r.status_code == 200
    assert r.json()["has_result"] is True
