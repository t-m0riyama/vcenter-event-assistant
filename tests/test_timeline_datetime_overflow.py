"""タイムラインの要求の、期間の from/to 以外の日時の検証（Issue #331）。

UTC に直すと日時の範囲を外れる値は 500 ではなく 422 にして、スナップショットを保存しない。
受け付けた値と保存済みの値は UTC（末尾 Z）で返す。画面は一覧を末尾 Z 必須のスキーマで読むので、
Z でない値が 1 件あると一覧ごと読めなくなる。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.api.schemas.base import to_utc_or_value_error
from vcenter_event_assistant.db.models import IncidentTimelineManualSnapshot
from vcenter_event_assistant.db.session import session_scope

_MANUAL_SNAPSHOT_URL = "/api/incident-timeline/snapshots/manual"
_VIEW_URL = "/api/incident-timeline/view"
# UTC に直すと datetime.min より前・datetime.max より後になる値
_NOT_REPRESENTABLE_IN_UTC = ["0001-01-01T00:00:00+01:00", "9999-12-31T23:30:00-01:00"]
_BASE_BODY: dict[str, object] = {
    "from": "2026-01-01T00:00:00Z",
    "to": "2026-01-02T00:00:00Z",
    "timestamp_utc": "2026-01-01T12:00:00Z",
    "operator_note": "probe",
}


async def _listed_items(client: AsyncClient) -> list[dict]:
    listed = await client.get(_MANUAL_SNAPSHOT_URL)
    assert listed.status_code == 200
    return listed.json()["items"]


async def _listed_item(client: AsyncClient, snapshot_id: str) -> dict:
    by_id = {item["snapshot_id"]: item for item in await _listed_items(client)}
    return by_id[snapshot_id]


def _error_locs(body: dict) -> list[list[object]]:
    return [error["loc"] for error in body["detail"]]


# --- 共有の検証 ---


def test_to_utc_or_value_error_normalizes_and_rejects_overflow() -> None:
    """タイムゾーンの無い値は UTC とみなし、+09:00 は UTC に直し、UTC に直せない値は ValueError にする。"""
    expected = datetime(2026, 1, 1, tzinfo=timezone.utc)
    naive = to_utc_or_value_error(datetime(2026, 1, 1))
    assert naive == expected
    assert naive.tzinfo is timezone.utc
    jst = to_utc_or_value_error(datetime(2026, 1, 1, 9, tzinfo=timezone(timedelta(hours=9))))
    assert jst == expected
    assert jst.tzinfo is timezone.utc
    with pytest.raises(ValueError, match="supported range"):
        to_utc_or_value_error(datetime.min.replace(tzinfo=timezone(timedelta(hours=1))))
    with pytest.raises(ValueError, match="supported range"):
        to_utc_or_value_error(datetime.max.replace(tzinfo=timezone(timedelta(hours=-1))))


# --- timestamp_utc ---


@pytest.mark.parametrize("value", _NOT_REPRESENTABLE_IN_UTC)
@pytest.mark.asyncio
async def test_manual_snapshot_rejects_timestamp_not_representable_in_utc(
    client: AsyncClient, value: str
) -> None:
    """timestamp_utc が UTC に直せないなら 422 にして、保存しない（500 の後に保存されて重複しない）。"""
    r = await client.post(_MANUAL_SNAPSHOT_URL, json={**_BASE_BODY, "timestamp_utc": value})
    assert r.status_code == 422
    assert _error_locs(r.json()) == [["body", "timestamp_utc"]]
    assert await _listed_items(client) == []


@pytest.mark.parametrize("value", ["2026-01-01T21:00:00+09:00", "2026-01-01T12:00:00"])
@pytest.mark.asyncio
async def test_manual_snapshot_returns_timestamp_in_utc(client: AsyncClient, value: str) -> None:
    """timestamp_utc が +09:00 やタイムゾーン無しでも、同じ瞬間を UTC の Z 付きで保存して返す。"""
    r = await client.post(_MANUAL_SNAPSHOT_URL, json={**_BASE_BODY, "timestamp_utc": value})
    assert r.status_code == 201
    created = r.json()
    assert created["timestamp_utc"] == "2026-01-01T12:00:00Z"
    item = await _listed_item(client, created["snapshot_id"])
    assert item["timestamp_utc"] == "2026-01-01T12:00:00Z"


# --- anchor ---


@pytest.mark.parametrize("value", _NOT_REPRESENTABLE_IN_UTC)
@pytest.mark.asyncio
async def test_view_rejects_anchor_not_representable_in_utc(client: AsyncClient, value: str) -> None:
    """/view の anchor が UTC に直せないなら 422（集計の中で 500 にしない）。"""
    r = await client.post(
        _VIEW_URL, json={"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z", "anchor": value}
    )
    assert r.status_code == 422
    assert _error_locs(r.json()) == [["body", "anchor"]]


@pytest.mark.asyncio
async def test_view_returns_anchor_in_utc(client: AsyncClient) -> None:
    """/view の anchor が +09:00 でも、応答の anchor_utc は UTC で返す。"""
    r = await client.post(
        _VIEW_URL,
        json={
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-02T00:00:00Z",
            "anchor": "2026-01-01T21:00:00+09:00",
        },
    )
    assert r.status_code == 200
    assert r.json()["anchor_utc"] == "2026-01-01T12:00:00Z"


@pytest.mark.parametrize("value", _NOT_REPRESENTABLE_IN_UTC)
@pytest.mark.asyncio
async def test_manual_snapshot_rejects_view_request_anchor_not_representable_in_utc(
    client: AsyncClient, value: str
) -> None:
    """スナップショットの view_request.anchor が UTC に直せないなら 422 にして、保存しない。"""
    r = await client.post(
        _MANUAL_SNAPSHOT_URL,
        json={
            **_BASE_BODY,
            "view_request": {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z", "anchor": value},
        },
    )
    assert r.status_code == 422
    assert _error_locs(r.json()) == [["body", "view_request", "anchor"]]
    assert await _listed_items(client) == []


# --- graph_context ---


@pytest.mark.parametrize(
    ("graph_context", "loc"),
    [
        ({"marker_timestamp_utc": _NOT_REPRESENTABLE_IN_UTC[0]}, ["body", "graph_context", "marker_timestamp_utc"]),
        (
            {"captured_range": {"from": _NOT_REPRESENTABLE_IN_UTC[0], "to": "2026-01-02T00:00:00Z"}},
            ["body", "graph_context", "captured_range", "from"],
        ),
        (
            {"captured_range": {"from": "2026-01-01T00:00:00Z", "to": _NOT_REPRESENTABLE_IN_UTC[1]}},
            ["body", "graph_context", "captured_range", "to"],
        ),
    ],
)
@pytest.mark.asyncio
async def test_manual_snapshot_rejects_graph_context_not_representable_in_utc(
    client: AsyncClient, graph_context: dict[str, object], loc: list[str]
) -> None:
    """graph_context の日時が UTC に直せないなら 422 にして、保存しない。"""
    r = await client.post(_MANUAL_SNAPSHOT_URL, json={**_BASE_BODY, "graph_context": graph_context})
    assert r.status_code == 422
    assert _error_locs(r.json()) == [loc]
    assert await _listed_items(client) == []


@pytest.mark.asyncio
async def test_manual_snapshot_returns_graph_context_in_utc(client: AsyncClient) -> None:
    """graph_context の日時が +09:00 やタイムゾーン無しでも、UTC の Z 付きで保存して返す。"""
    r = await client.post(
        _MANUAL_SNAPSHOT_URL,
        json={
            **_BASE_BODY,
            "graph_context": {
                "marker_timestamp_utc": "2026-01-01T21:00:00+09:00",
                "captured_range": {"from": "2026-01-01T00:00:00", "to": "2026-01-02T09:00:00+09:00"},
            },
        },
    )
    assert r.status_code == 201
    created = r.json()
    for graph_context in (created["graph_context"], (await _listed_item(client, created["snapshot_id"]))["graph_context"]):
        assert graph_context["marker_timestamp_utc"] == "2026-01-01T12:00:00Z"
        assert graph_context["captured_range"] == {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"}


async def _insert_snapshot_with_graph_context(graph_context: dict[str, object]) -> str:
    """変更前に保存できた graph_context を持つ行を、API を通さずに入れる。"""
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with session_scope() as session:
        snapshot = IncidentTimelineManualSnapshot(
            from_time=t0,
            to_time=t0 + timedelta(days=1),
            timestamp_utc=t0,
            operator_note="変更前に保存した行",
            build_request_payload={"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"},
            graph_context=graph_context,
        )
        session.add(snapshot)
        await session.flush()
        return str(snapshot.id)


@pytest.mark.asyncio
async def test_saved_graph_context_without_utc_is_read_as_utc(client: AsyncClient) -> None:
    """+09:00 やタイムゾーン無しで保存済みの graph_context も、一覧と詳細では UTC の Z 付きで返す。"""
    snapshot_id = await _insert_snapshot_with_graph_context(
        {
            "metric_key": "host.cpu.usage_pct",
            "marker_timestamp_utc": "2026-01-01T21:00:00+09:00",
            "captured_range": {"from": "2026-01-01T00:00:00", "to": "2026-01-02T09:00:00+09:00"},
        }
    )
    detail = await client.get(f"{_MANUAL_SNAPSHOT_URL}/{snapshot_id}")
    assert detail.status_code == 200
    for graph_context in ((await _listed_item(client, snapshot_id))["graph_context"], detail.json()["graph_context"]):
        assert graph_context["metric_key"] == "host.cpu.usage_pct"
        assert graph_context["marker_timestamp_utc"] == "2026-01-01T12:00:00Z"
        assert graph_context["captured_range"] == {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"}


@pytest.mark.parametrize(
    "graph_context",
    [
        {"marker_timestamp_utc": _NOT_REPRESENTABLE_IN_UTC[0]},
        {"captured_range": {"from": "2026-01-01T00:00:00Z", "to": _NOT_REPRESENTABLE_IN_UTC[1]}},
    ],
)
@pytest.mark.asyncio
async def test_saved_graph_context_not_representable_in_utc_is_returned_as_null(
    client: AsyncClient, graph_context: dict[str, object]
) -> None:
    """UTC に直せない graph_context を持つ保存済みの行も、一覧と詳細を 500 にせず、graph_context を null で返す。"""
    snapshot_id = await _insert_snapshot_with_graph_context(graph_context)
    assert (await _listed_item(client, snapshot_id))["graph_context"] is None
    detail = await client.get(f"{_MANUAL_SNAPSHOT_URL}/{snapshot_id}")
    assert detail.status_code == 200
    assert detail.json()["graph_context"] is None
