"""手動スナップショットに view の結果を保存する機能（POST /snapshots/manual の view_request）のテスト。"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
import re

from sqlalchemy import event, func, select, text

from vcenter_event_assistant.db.models import EventRecord, IncidentTimelineManualSnapshot, VCenter
from vcenter_event_assistant.api.routes import incident_timeline as route_module
from vcenter_event_assistant.db.session import get_engine, session_scope
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


async def _seed_events(count: int = 2, *, message: str | None = None) -> uuid.UUID:
    vid = uuid.uuid4()
    async with session_scope() as session:
        session.add(VCenter(id=vid, name=f"vc-{vid}", host="h", port=443, username="u", password="p"))
        for i in range(count):
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=T0 + timedelta(minutes=10 * (i + 1)),
                    event_type=f"Type{i}",
                    message=message or f"message {i}",
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


_MINIMAL_RESULT = {
    "from_utc": "2026-03-22T00:00:00Z",
    "to_utc": "2026-03-22T02:00:00Z",
    "bucket_seconds": 60,
    "overview": [],
    "items": [],
    "truncated": False,
    "total_items": 0,
    "highlights": {"first_signal": None, "top_entities": [], "new_event_types": []},
}


@pytest.mark.asyncio
async def test_long_details_are_cut_in_the_stored_copy_only(client: AsyncClient) -> None:
    await _seed_events(2, message="あ" * 5000)
    live = (await client.post("/api/incident-timeline/view", json=_view_request())).json()
    assert len(live["items"][0]["detail"]) == 5000  # view API の応答は変えない

    created = await client.post(URL, json=_body(view_request=_view_request()))
    assert created.status_code == 201
    detail = (await client.get(f"{URL}/{created.json()['snapshot_id']}")).json()["result"]
    for item in [*detail["items"], detail["highlights"]["first_signal"]]:
        assert item["detail"].startswith("あ" * 2000)
        assert len(item["detail"]) < 2100
        assert item["detail"] != "あ" * 2000  # 切ったことが分かる印が付く
    # 短い detail はそのまま
    assert route_module._truncate_details_for_storage({"detail": "short"}) == {"detail": "short"}


@pytest.mark.asyncio
async def test_result_over_the_size_limit_is_413_and_not_saved(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_events(3)
    monkeypatch.setattr(route_module, "MAX_SNAPSHOT_RESULT_BYTES", 500)
    r = await client.post(URL, json=_body(view_request=_view_request()))
    assert r.status_code == 413
    assert "期間" in r.json()["detail"]
    assert await _snapshot_count() == 0


@pytest.mark.asyncio
async def test_size_limit_counts_utf8_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    assert route_module.MAX_SNAPSHOT_RESULT_BYTES == 8 * 1024 * 1024
    # 日本語は 1 文字 3 バイトで数える（上限は文字数ではなくバイト数）
    assert route_module._json_utf8_size({"a": "あ" * 10}) == len('{"a": "'.encode()) + 30 + 2


@pytest.mark.asyncio
async def test_json_columns_are_stored_without_unicode_escapes(client: AsyncClient) -> None:
    await _seed_events(1, message="日本語のメッセージ")
    created = await client.post(URL, json=_body(operator_note="メモ", view_request=_view_request()))
    assert created.status_code == 201
    async with get_engine().connect() as conn:
        raw = (await conn.execute(text("SELECT result_payload FROM incident_timeline_manual_snapshots"))).scalar_one()
    assert "日本語のメッセージ" in raw
    assert "\\u" not in raw
    # 読み戻しは同じ値
    detail = (await client.get(f"{URL}/{created.json()['snapshot_id']}")).json()
    assert detail["result"]["items"][0]["detail"] == "日本語のメッセージ"


@pytest.mark.asyncio
async def test_view_request_is_read_leniently(client: AsyncClient) -> None:
    """将来の項目の追加・削除や範囲の検査の変更があっても、保存済みの結果を読める。"""
    sid = await _insert_row(
        result_payload=_MINIMAL_RESULT,
        view_request_payload={
            "from": "2026-03-22T02:00:00Z",  # 逆順（いまの検査なら通らない）
            "to": "2026-03-22T00:00:00Z",
            "some_future_field": 1,
        },
    )
    detail = (await client.get(f"{URL}/{sid}")).json()
    assert detail["has_result"] is True
    assert detail["result"]["bucket_seconds"] == 60
    highlights = detail["result"]["highlights"]
    assert highlights["detected_patterns"] == []
    assert highlights["detected_patterns_total"] == 0
    assert highlights["omitted_patterns"] == []
    assert detail["view_request"]["from"] == "2026-03-22T02:00:00Z"
    assert "some_future_field" not in detail["view_request"]
    assert (await client.get(URL)).json()["items"][0]["view_request"] is not None


@pytest.mark.asyncio
async def test_created_at_is_returned_by_create_list_and_detail(client: AsyncClient) -> None:
    created = await client.post(URL, json=_body(timestamp_utc="2020-01-01T00:00:00Z"))
    assert created.status_code == 201
    created_at = created.json()["created_at"]
    assert created_at is not None
    assert not created_at.startswith("2020-01-01")  # クライアントの値ではなくサーバの保存時刻
    assert (await client.get(URL)).json()["items"][0]["created_at"] == created_at
    assert (await client.get(f"{URL}/{created.json()['snapshot_id']}")).json()["created_at"] == created_at


@pytest.mark.asyncio
async def test_list_query_does_not_select_the_result_body(client: AsyncClient) -> None:
    await _seed_events()
    await client.post(URL, json=_body(view_request=_view_request()))
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    sync_engine = get_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        r = await client.get(URL)
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)
    assert r.status_code == 200
    selects = [s for s in statements if "FROM incident_timeline_manual_snapshots" in s and "count(" not in s]
    assert selects
    for stmt in selects:
        # result_payload は IS NOT NULL の判定にだけ使い、本体は読まない
        assert re.findall(r"result_payload(?! IS NOT NULL)", stmt) == []


@pytest.mark.asyncio
async def test_unspecified_graph_context_fields_are_returned_as_null(client: AsyncClient) -> None:
    """フロントの zod が null を受け付ける前提。ここが変わったら frontend の実応答フィクスチャも直す
    （frontend/src/api/schemas/incidentTimelineSnapshotResult.test.ts の ACTUAL_*）。"""
    body = _body(
        graph_context={
            "marker_timestamp_utc": "2026-03-22T03:00:00Z",
            "captured_range": {"from": "2026-03-22T00:00:00Z", "to": "2026-03-22T02:00:00Z"},
        },
    )
    created = await client.post(URL, json=body)
    assert created.status_code == 201
    expected = {
        "metric_key": None,
        "chart_event_type": None,
        "marker_timestamp_utc": "2026-03-22T03:00:00Z",
        "vcenter_id": None,
        "captured_range": {"from": "2026-03-22T00:00:00Z", "to": "2026-03-22T02:00:00Z"},
    }
    assert created.json()["graph_context"] == expected
    assert (await client.get(URL)).json()["items"][0]["graph_context"] == expected
    assert (await client.get(f"{URL}/{created.json()['snapshot_id']}")).json()["graph_context"] == expected
