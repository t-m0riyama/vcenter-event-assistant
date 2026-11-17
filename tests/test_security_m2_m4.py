"""M-2 / M-3 / M-4 security API guards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient, Response

from vcenter_event_assistant.api.schemas.chat import (
    ChatRequest,
    IncidentTimelineManualSnapshotCreateRequest,
)
from vcenter_event_assistant.api.schemas.incident_timeline_view import (
    IncidentTimelineViewRequest,
    normalize_time_span,
)
from vcenter_event_assistant.db.models import IncidentTimelineManualSnapshot
from vcenter_event_assistant.db.session import session_scope


@pytest.mark.asyncio
async def test_alert_history_rejects_oversized_limit(client: AsyncClient) -> None:
    r = await client.get("/api/alerts/history", params={"limit": 5000})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_alert_rules_import_rejects_empty_delete(client: AsyncClient) -> None:
    r = await client.post(
        "/api/alerts/rules/import",
        json={"rules": [], "delete_rules_not_in_import": True},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_chat_rejects_excessive_time_range(client: AsyncClient) -> None:
    r = await client.post(
        "/api/chat/preview",
        json={
            "from": "2020-01-01T00:00:00Z",
            "to": "2026-01-01T00:00:00Z",
            "messages": [{"role": "user", "content": "test"}],
        },
    )
    assert r.status_code == 422
    detail = str(r.json().get("detail", ""))
    assert "90" in detail


@pytest.mark.asyncio
async def test_manual_snapshot_rejects_excessive_build_request_range(client: AsyncClient) -> None:
    """IncidentTimelineBuildRequest の期間の上限（90 日）を、スナップショットの保存の build_request_payload で確かめる。

    外側の from/to は短く正しい期間にし、422 が入れ子の条件から出ることを確かめる。
    """
    r = await client.post(
        "/api/incident-timeline/snapshots/manual",
        json={
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-02T00:00:00Z",
            "timestamp_utc": "2026-01-01T12:00:00Z",
            "operator_note": "期間の上限の確認",
            "build_request_payload": {
                "from": "2020-01-01T00:00:00Z",
                "to": "2026-01-01T00:00:00Z",
            },
        },
    )
    assert r.status_code == 422
    assert all("build_request_payload" in error["loc"] for error in r.json()["detail"])
    detail = str(r.json().get("detail", ""))
    assert "90" in detail


_MANUAL_SNAPSHOT_URL = "/api/incident-timeline/snapshots/manual"
# 外側の from/to だけ 90 日を超える本文（Issue #330 の再現）
_OUTER_TOO_LONG: dict[str, object] = {
    "from": "2020-01-01T00:00:00Z",
    "to": "2026-01-01T00:00:00Z",
    "timestamp_utc": "2026-01-01T00:00:00Z",
    "operator_note": "probe",
}
_SHORT_RANGE = {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"}


def _assert_rejected_by_outer_range(r: Response) -> None:
    """422 で、エラーが入れ子の条件ではなく外側の from/to の検証から出たことを確かめる。"""
    assert r.status_code == 422
    errors = r.json()["detail"]
    assert errors
    for error in errors:
        assert "build_request_payload" not in error["loc"]
        assert "view_request" not in error["loc"]
        assert "90" in error["msg"]


async def _listed_items(client: AsyncClient) -> list[dict]:
    listed = await client.get(_MANUAL_SNAPSHOT_URL)
    assert listed.status_code == 200
    return listed.json()["items"]


async def _listed_item(client: AsyncClient, snapshot_id: str) -> dict:
    by_id = {item["snapshot_id"]: item for item in await _listed_items(client)}
    return by_id[snapshot_id]


@pytest.mark.asyncio
async def test_manual_snapshot_rejects_excessive_outer_range(client: AsyncClient) -> None:
    """view_request も build_request_payload も無いとき、外側の from/to の 90 日超は 422（500 にしない）。"""
    r = await client.post(_MANUAL_SNAPSHOT_URL, json=_OUTER_TOO_LONG)
    _assert_rejected_by_outer_range(r)


@pytest.mark.asyncio
async def test_manual_snapshot_rejects_excessive_outer_range_with_view_request(
    client: AsyncClient,
) -> None:
    """view_request が 90 日以内でも、外側の from/to が 90 日を超えれば 422 にし、保存しない。"""
    r = await client.post(_MANUAL_SNAPSHOT_URL, json={**_OUTER_TOO_LONG, "view_request": _SHORT_RANGE})
    _assert_rejected_by_outer_range(r)
    assert await _listed_items(client) == []


@pytest.mark.asyncio
async def test_manual_snapshot_rejects_excessive_outer_range_with_build_request_payload(
    client: AsyncClient,
) -> None:
    """build_request_payload が 90 日以内でも、外側の from/to が 90 日を超えれば 422 にし、保存しない。"""
    r = await client.post(
        _MANUAL_SNAPSHOT_URL, json={**_OUTER_TOO_LONG, "build_request_payload": _SHORT_RANGE}
    )
    _assert_rejected_by_outer_range(r)
    assert await _listed_items(client) == []


@pytest.mark.asyncio
async def test_manual_snapshot_accepts_outer_range_of_exactly_90_days(client: AsyncClient) -> None:
    """外側の from/to がちょうど 90 日なら保存する。"""
    r = await client.post(
        _MANUAL_SNAPSHOT_URL,
        json={**_OUTER_TOO_LONG, "from": "2026-01-01T00:00:00Z", "to": "2026-04-01T00:00:00Z"},
    )
    assert r.status_code == 201


async def _post_and_assert_utc_range(
    client: AsyncClient, body: dict[str, object], *, expected_from: str, expected_to: str
) -> dict:
    """保存の応答と一覧の両方で、from/to が UTC の Z 付きの文字列で返ることを確かめ、一覧の 1 件を返す。

    画面は一覧の build_request_payload を末尾 Z 必須のスキーマで読むので、Z でないと一覧ごと読めなくなる。
    """
    r = await client.post(_MANUAL_SNAPSHOT_URL, json=body)
    assert r.status_code == 201
    created = r.json()
    assert created["build_request_payload"]["from"] == expected_from
    assert created["build_request_payload"]["to"] == expected_to

    item = await _listed_item(client, created["snapshot_id"])
    assert item["from"] == expected_from
    assert item["to"] == expected_to
    assert item["build_request_payload"]["from"] == expected_from
    assert item["build_request_payload"]["to"] == expected_to
    return item


@pytest.mark.asyncio
async def test_manual_snapshot_accepts_outer_from_without_timezone(client: AsyncClient) -> None:
    """外側の from だけタイムゾーンが無くても UTC とみなし、保存して Z 付きで返す。"""
    await _post_and_assert_utc_range(
        client,
        {
            "from": "2026-01-01T00:00:00",
            "to": "2026-01-02T00:00:00Z",
            "timestamp_utc": "2026-01-01T12:00:00Z",
            "operator_note": "タイムゾーンの混在",
        },
        expected_from="2026-01-01T00:00:00Z",
        expected_to="2026-01-02T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_manual_snapshot_accepts_outer_to_without_timezone(client: AsyncClient) -> None:
    """外側の to だけタイムゾーンが無くても UTC とみなし、保存して Z 付きで返す。"""
    await _post_and_assert_utc_range(
        client,
        {
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-02T00:00:00",
            "timestamp_utc": "2026-01-01T12:00:00Z",
            "operator_note": "タイムゾーンの混在",
        },
        expected_from="2026-01-01T00:00:00Z",
        expected_to="2026-01-02T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_manual_snapshot_converts_outer_offset_to_utc(client: AsyncClient) -> None:
    """外側が +09:00 なら、同じ瞬間を UTC の Z 付きで保存して返す。"""
    await _post_and_assert_utc_range(
        client,
        {
            "from": "2026-01-01T09:00:00+09:00",
            "to": "2026-01-02T09:00:00+09:00",
            "timestamp_utc": "2026-01-01T12:00:00Z",
            "operator_note": "オフセット付き",
        },
        expected_from="2026-01-01T00:00:00Z",
        expected_to="2026-01-02T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_manual_snapshot_converts_view_request_offset_to_utc(client: AsyncClient) -> None:
    """view_request が +09:00 なら、保存する条件（view_request と build_request_payload）も UTC の Z 付きになる。"""
    item = await _post_and_assert_utc_range(
        client,
        {
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-02T00:00:00Z",
            "timestamp_utc": "2026-01-01T12:00:00Z",
            "operator_note": "オフセット付きの view_request",
            "view_request": {"from": "2026-01-01T10:00:00+09:00", "to": "2026-01-01T12:00:00+09:00"},
        },
        expected_from="2026-01-01T01:00:00Z",
        expected_to="2026-01-01T03:00:00Z",
    )
    assert item["view_request"]["from"] == "2026-01-01T01:00:00Z"
    assert item["view_request"]["to"] == "2026-01-01T03:00:00Z"


@pytest.mark.asyncio
async def test_saved_build_request_payload_without_utc_is_read_as_utc(client: AsyncClient) -> None:
    """タイムゾーン無しや +09:00 で保存済みの build_request_payload も、一覧では UTC の Z 付きで返す。"""
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with session_scope() as session:
        snapshot = IncidentTimelineManualSnapshot(
            from_time=t0,
            to_time=t0 + timedelta(days=1),
            timestamp_utc=t0,
            operator_note="変更前に保存した行",
            build_request_payload={"from": "2026-01-01T00:00:00", "to": "2026-01-02T09:00:00+09:00"},
        )
        session.add(snapshot)
        await session.flush()
        snapshot_id = str(snapshot.id)

    item = await _listed_item(client, snapshot_id)
    assert item["build_request_payload"]["from"] == "2026-01-01T00:00:00Z"
    assert item["build_request_payload"]["to"] == "2026-01-02T00:00:00Z"


@pytest.mark.parametrize(
    "saved_payload",
    [
        {"from": "0001-01-01T00:00:00+01:00", "to": "0001-01-02T00:00:00+01:00"},
        {"from": "9999-12-30T23:30:00-01:00", "to": "9999-12-31T23:30:00-01:00"},
    ],
)
@pytest.mark.asyncio
async def test_saved_build_request_payload_not_representable_in_utc_falls_back_to_columns(
    client: AsyncClient, saved_payload: dict[str, str]
) -> None:
    """UTC に直せない build_request_payload を持つ保存済みの行も、一覧と詳細を 500 にせず、列の期間で返す。"""
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with session_scope() as session:
        snapshot = IncidentTimelineManualSnapshot(
            from_time=t0,
            to_time=t0 + timedelta(days=1),
            timestamp_utc=t0,
            operator_note="変更前に保存できた行",
            build_request_payload=saved_payload,
        )
        session.add(snapshot)
        await session.flush()
        snapshot_id = str(snapshot.id)

    item = await _listed_item(client, snapshot_id)
    assert item["build_request_payload"]["from"] == "2026-01-01T00:00:00Z"
    assert item["build_request_payload"]["to"] == "2026-01-02T00:00:00Z"

    detail = await client.get(f"{_MANUAL_SNAPSHOT_URL}/{snapshot_id}")
    assert detail.status_code == 200
    assert detail.json()["build_request_payload"]["from"] == "2026-01-01T00:00:00Z"
    assert detail.json()["build_request_payload"]["to"] == "2026-01-02T00:00:00Z"


# タイムゾーン無し・+09:00・Z の、どれも 2026-01-01T00:00:00Z〜2026-01-02T00:00:00Z を指す組
_SAME_RANGE_IN_VARIOUS_ZONES = [
    ("2026-01-01T00:00:00", "2026-01-02T00:00:00Z"),
    ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00"),
    ("2026-01-01T09:00:00+09:00", "2026-01-02T09:00:00+09:00"),
]
_EXPECTED_FROM = datetime(2026, 1, 1, tzinfo=timezone.utc)
_EXPECTED_TO = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _assert_utc_range(
    model: ChatRequest | IncidentTimelineViewRequest | IncidentTimelineManualSnapshotCreateRequest,
) -> None:
    """from_time / to_time が timezone.utc で、正しい瞬間を指すことを確かめる（DB の列に入る値の確認）。"""
    assert model.from_time.tzinfo is timezone.utc
    assert model.to_time.tzinfo is timezone.utc
    assert model.from_time == _EXPECTED_FROM
    assert model.to_time == _EXPECTED_TO


@pytest.mark.parametrize(("from_value", "to_value"), _SAME_RANGE_IN_VARIOUS_ZONES)
def test_manual_snapshot_request_model_normalizes_ranges_to_utc(from_value: str, to_value: str) -> None:
    """手動スナップショットの外側と view_request の from/to を UTC に揃える。"""
    body = IncidentTimelineManualSnapshotCreateRequest.model_validate(
        {
            "from": from_value,
            "to": to_value,
            "timestamp_utc": "2026-01-01T12:00:00Z",
            "operator_note": "UTC に揃える",
            "view_request": {"from": from_value, "to": to_value},
        }
    )
    _assert_utc_range(body)
    assert body.view_request is not None
    _assert_utc_range(body.view_request)


@pytest.mark.parametrize(("from_value", "to_value"), _SAME_RANGE_IN_VARIOUS_ZONES)
def test_chat_and_view_request_models_normalize_ranges_to_utc(from_value: str, to_value: str) -> None:
    """ChatRequest と IncidentTimelineViewRequest も from/to を UTC に揃える。"""
    chat = ChatRequest.model_validate(
        {"from": from_value, "to": to_value, "messages": [{"role": "user", "content": "test"}]}
    )
    _assert_utc_range(chat)
    _assert_utc_range(IncidentTimelineViewRequest.model_validate({"from": from_value, "to": to_value}))


@pytest.mark.asyncio
async def test_manual_snapshot_rejects_outer_from_without_timezone_after_to(client: AsyncClient) -> None:
    """外側の from だけタイムゾーンが無く from >= to なら 422（比較で 500 にしない）。"""
    r = await client.post(
        _MANUAL_SNAPSHOT_URL,
        json={
            "from": "2026-01-03T00:00:00",
            "to": "2026-01-02T00:00:00Z",
            "timestamp_utc": "2026-01-01T12:00:00Z",
            "operator_note": "タイムゾーンの混在",
        },
    )
    assert r.status_code == 422
    errors = r.json()["detail"]
    assert [error["loc"] for error in errors] == [["body"]]
    assert "from must be before to" in errors[0]["msg"]


@pytest.mark.asyncio
async def test_manual_snapshot_rejects_outer_range_not_representable_in_utc(client: AsyncClient) -> None:
    """UTC に直すと datetime の範囲を外れる from/to は 422（OverflowError で 500 にしない）。"""
    r = await client.post(
        _MANUAL_SNAPSHOT_URL,
        json={
            "from": "0001-01-01T00:00:00+01:00",
            "to": "0001-01-02T00:00:00+01:00",
            "timestamp_utc": "2026-01-01T12:00:00Z",
            "operator_note": "範囲外",
        },
    )
    assert r.status_code == 422
    assert [error["loc"] for error in r.json()["detail"]] == [["body"]]
    assert await _listed_items(client) == []


def test_normalize_time_span_returns_utc_for_mixed_timezones() -> None:
    """片方だけタイムゾーンが無くても TypeError にせず、両方を UTC に揃えて返す。"""
    jst = timezone(timedelta(hours=9))
    ft, tt = normalize_time_span(datetime(2026, 1, 1), datetime(2026, 1, 2, 9, tzinfo=jst))
    assert ft == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert tt == datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert ft.tzinfo is timezone.utc
    assert tt.tzinfo is timezone.utc
    with pytest.raises(ValueError, match="from"):
        normalize_time_span(datetime(2026, 1, 3), datetime(2026, 1, 2, tzinfo=timezone.utc))


def test_normalize_time_span_allows_exactly_90_days() -> None:
    """90 日ちょうどは通し、それを超えたら拒否する。"""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    normalize_time_span(start, start + timedelta(days=90))
    with pytest.raises(ValueError, match="90"):
        normalize_time_span(start, start + timedelta(days=90, seconds=1))


def test_normalize_time_span_rejects_values_not_representable_in_utc() -> None:
    """UTC に直すと範囲外になる値は OverflowError ではなく ValueError にする。"""
    plus_one = timezone(timedelta(hours=1))
    with pytest.raises(ValueError):
        normalize_time_span(datetime.min.replace(tzinfo=plus_one), datetime(1, 1, 2, tzinfo=plus_one))
