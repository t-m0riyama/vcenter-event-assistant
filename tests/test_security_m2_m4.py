"""M-2 / M-3 / M-4 security API guards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient, Response

from vcenter_event_assistant.api.schemas.incident_timeline_view import check_time_span


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
    assert "90" in str(errors)


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

    listed = await client.get(_MANUAL_SNAPSHOT_URL)
    assert listed.status_code == 200
    assert listed.json()["items"] == []


@pytest.mark.asyncio
async def test_manual_snapshot_rejects_excessive_outer_range_with_build_request_payload(
    client: AsyncClient,
) -> None:
    """build_request_payload が 90 日以内でも、外側の from/to が 90 日を超えれば 422。"""
    r = await client.post(
        _MANUAL_SNAPSHOT_URL, json={**_OUTER_TOO_LONG, "build_request_payload": _SHORT_RANGE}
    )
    _assert_rejected_by_outer_range(r)


@pytest.mark.asyncio
async def test_manual_snapshot_accepts_outer_from_without_timezone(client: AsyncClient) -> None:
    """外側の from だけタイムゾーンが無くても UTC とみなし、期間が正しければ保存する。"""
    r = await client.post(
        _MANUAL_SNAPSHOT_URL,
        json={
            "from": "2026-01-01T00:00:00",
            "to": "2026-01-02T00:00:00Z",
            "timestamp_utc": "2026-01-01T12:00:00Z",
            "operator_note": "タイムゾーンの混在",
        },
    )
    assert r.status_code == 201


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


def test_check_time_span_accepts_mixed_timezones() -> None:
    """片方だけタイムゾーンが無くても TypeError にせず、UTC とみなして比べる。"""
    check_time_span(datetime(2026, 1, 1), datetime(2026, 1, 2, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="from"):
        check_time_span(datetime(2026, 1, 3), datetime(2026, 1, 2, tzinfo=timezone.utc))


def test_check_time_span_allows_exactly_90_days() -> None:
    """90 日ちょうどは通し、それを超えたら拒否する。"""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    check_time_span(start, start + timedelta(days=90))
    with pytest.raises(ValueError, match="90"):
        check_time_span(start, start + timedelta(days=90, seconds=1))
