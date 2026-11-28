"""調査資料の内容と出力 API を確かめる。"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from threading import Event, get_ident
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from vcenter_event_assistant.api.routes import incident_timeline as routes
from vcenter_event_assistant.api.schemas.incident_timeline_view import (
    IncidentTimelineViewResponse,
)
from vcenter_event_assistant.db.models import IncidentTimelineManualSnapshot, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.services.chat.aggregation_limiter import aggregation_slot
from vcenter_event_assistant.services.incident_timeline_view import (
    TimelineEntry,
    select_within_limit,
)
from vcenter_event_assistant.settings_binding import require_settings

POST = "/api/incident-timeline/export"
MANUAL = "/api/incident-timeline/snapshots/manual"
FROM = "2026-11-01T05:50:00Z"
TO = "2026-11-01T06:10:00Z"
BODY = {"from": FROM, "to": TO}
ZONE = "America/New_York"
VC = uuid.UUID("9a56aa1d-aec6-47ed-9801-ba7ff31d944c")
MISSING = (
    "結果が保存されていません。開いて再集計してから、今の表示を出力してください。"
    "元データの保持期間（既定 7 日）を過ぎていると、再集計の結果は空か一部になります"
)


def _item(index: int = 1, **fields: object) -> dict:
    return {
        "id": f"event:{index}",
        "kind": "event",
        "level": "warning",
        "timestamp_utc": FROM,
        "title": f"出来事 {index}",
        **fields,
    }


def _result(**fields: object) -> IncidentTimelineViewResponse:
    return IncidentTimelineViewResponse.model_validate(
        {
            "from_utc": FROM,
            "to_utc": TO,
            "anchor_utc": FROM,
            "bucket_seconds": 60,
            "overview": [],
            "items": [],
            "truncated": False,
            "total_items": 0,
            "highlights": {},
            **fields,
        }
    )


async def _snapshot(
    result: IncidentTimelineViewResponse | dict | None = None,
    *,
    operator_note: str = "調査を引き継ぐ\r\n````\r![p](https://evil.example/p) @octocat\x7f\u202e",
    **fields: object,
) -> str:
    sid = uuid.uuid4()
    async with session_scope() as session:
        session.add(
            IncidentTimelineManualSnapshot(
                id=sid,
                from_time=datetime.fromisoformat(FROM),
                to_time=datetime.fromisoformat(TO),
                timestamp_utc=datetime.fromisoformat(FROM),
                created_at=datetime.fromisoformat(TO),
                operator_note=operator_note,
                result_payload=result.model_dump(mode="json")
                if isinstance(result, IncidentTimelineViewResponse)
                else result,
                **fields,
            )
        )
    return f"{MANUAL}/{sid}/export"


def _aggregate_with(
    monkeypatch: pytest.MonkeyPatch, result: IncidentTimelineViewResponse
) -> None:
    async def aggregate(*args, **kwargs):  # type: ignore[no-untyped-def]
        return result

    monkeypatch.setattr(routes, "build_incident_timeline_view", aggregate)


def _archive(content: bytes) -> dict[str, bytes]:
    with ZipFile(io.BytesIO(content)) as archive:
        assert archive.namelist() == [
            "report.md",
            "items.csv",
            "overview.csv",
            "result.json",
            "conditions.json",
        ]
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.asyncio
async def test_report_reads_legacy_patterns_and_shows_device_for_pdl(viewer_client: AsyncClient) -> None:
    pattern = {
        "pattern_id": "apd-timeout",
        "title": "APD のタイムアウト",
        "description": "",
        "level": "critical",
        "vcenter_id": str(VC),
        "entity_moid": "host-1",
        "first_utc": FROM,
        "last_utc": TO,
        "event_count": 1,
        "event_ids": [1],
    }
    payload = _result().model_dump(mode="json")
    payload["highlights"]["detected_patterns"] = [
        pattern,
        {**pattern, "pattern_id": "pdl", "title": "PDL", "subject": "device", "device_id": "naa.123"},
        {**pattern, "pattern_id": "pdl", "title": "PDL", "subject": "device", "device_id": None},
    ]
    parsed = IncidentTimelineViewResponse.model_validate(payload)
    old, *_ = parsed.highlights.detected_patterns
    assert (old.subject, old.device_id) == (None, None)

    response = await viewer_client.get(await _snapshot(payload), params={"format": "md"})
    assert response.status_code == 200
    pattern_lines = [line for line in response.text.splitlines() if line.startswith("- ` APD") or line.startswith("- ` PDL")]
    assert len(pattern_lines) == 3
    assert "デバイスを特定できません" not in pattern_lines[0]
    assert "` naa.123 `" in pattern_lines[1]
    assert "デバイスを特定できません" in pattern_lines[2]


@pytest.mark.asyncio
async def test_saved_report_and_archive(viewer_client: AsyncClient) -> None:
    signal = _item(
        vcenter_id=str(VC),
        vcenter_name="demo-vcenter",
        entity_name="@web|01",
        entity_type="+Host",
        score=-2,
        title="=接続エラー",
        detail="-詳細",
        end_utc=TO,
        ref={
            "event_type": "=HostError",
            "entity_moid": "@host-1",
            "event_id": 12,
            "peak_at_utc": TO,
            "peak_value": -1.5,
        },
    )
    result = _result(
        items=[signal],
        total_items=5,
        truncated=True,
        overview=[
            {
                "bucket_start_utc": FROM,
                "event_total": 3,
                "event_notable": 1,
                "alert": 0,
                "metric_breach": 0,
                "log_error": 2,
            }
        ],
        omitted_sources=[{"source": "log", "reason": "too_many_rows"}],
        highlights={
            "first_signal": signal,
            "top_entities": [
                {"entity_name": "demo-esxi-01", "item_count": 2, "first_seen_utc": FROM}
            ],
            "new_event_types": [
                {
                    "event_type": "HostEvent",
                    "count": 1,
                    "first_seen_utc": TO,
                    "max_score": 65,
                }
            ],
            "detected_patterns": [
                {
                    "pattern_id": "network",
                    "title": "接続の異常",
                    "description": "連続して発生",
                    "level": "warning",
                    "vcenter_id": str(VC),
                    "vcenter_name": "pattern-vc",
                    "entity_moid": "host-1",
                    "first_utc": FROM,
                    "last_utc": TO,
                    "event_count": 3,
                    "event_ids": [12],
                }
            ],
            "detected_patterns_total": 2,
            "omitted_patterns": ["test-omitted"],
        },
    )
    request = {
        **BODY,
        "vcenter_id": str(VC),
        "entity": "demo|esxi",
        "entity_moid": "host-1",
        "sources": ["event", "metric"],
        "min_score": 30,
        "metric_threshold_cpu_pct": 80,
        "metric_threshold_memory_pct": 85,
        "metric_threshold_disk_pct": 75,
    }
    url = await _snapshot(result, view_request_payload=request)
    snapshot_id = url.split("/")[-2]
    response = await viewer_client.get(url, params={"format": "zip", "time_zone": ZONE})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    disposition = response.headers["content-disposition"]
    timestamp = re.fullmatch(
        rf'attachment; filename="timeline-(\d{{8}}-\d{{6}})-{snapshot_id[:8]}\.zip"',
        disposition,
    )
    assert timestamp
    local = datetime.strptime(timestamp[1], "%Y%m%d-%H%M%S")
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert all(
            info.date_time
            == local.replace(second=local.second // 2 * 2).timetuple()[:6]
            for info in archive.infolist()
        )
    files = _archive(response.content)
    assert json.loads(files["result.json"]) == result.model_dump(mode="json")
    conditions = json.loads(files["conditions.json"])
    assert conditions["snapshot_id"] == snapshot_id
    assert conditions["view_request"]["entity"] == "demo|esxi"
    assert conditions["operator_note"].startswith("調査を引き継ぐ")
    for name in ("items.csv", "overview.csv"):
        assert files[name].startswith(b"\xef\xbb\xbf")
    (row,) = list(csv.DictReader(io.StringIO(files["items.csv"].decode("utf-8-sig"))))
    assert row == {
        "timestamp": "2026/11/01 01:50:00",
        "timestamp_utc_offset": "-04:00",
        "kind_label": "イベント",
        "kind": "event",
        "level": "warning",
        "vcenter_name": "demo-vcenter",
        "entity_name": "'@web|01",
        "title": "'=接続エラー",
        "detail": "'-詳細",
        "count": "1",
        "score": "-2",
        "id": "event:1",
        "entity_type": "'+Host",
        "vcenter_id": str(VC),
        "entity_moid": "'@host-1",
        "end": "2026/11/01 01:10:00",
        "end_utc_offset": "-05:00",
        "event_id": "12",
        "event_type": "'=HostError",
        "alert_history_id": "",
        "alert_rule_id": "",
        "alert_rule_name": "",
        "alert_rule_type": "",
        "alert_state": "",
        "metric_key": "",
        "log_id": "",
        "threshold_pct": "",
        "peak_value": "-1.5",
        "peak_at": "2026/11/01 01:10:00",
        "peak_at_utc_offset": "-05:00",
        "sample_count": "",
        "continues_from_before": "",
        "continues_after": "",
        "time_zone": ZONE,
        "config_change_kind": "",
    }
    (overview,) = list(
        csv.DictReader(io.StringIO(files["overview.csv"].decode("utf-8-sig")))
    )
    assert overview == {
        "bucket_start": "2026/11/01 01:50:00",
        "bucket_start_utc_offset": "-04:00",
        "event_total": "3",
        "event_notable": "1",
        "alert": "0",
        "metric_breach": "0",
        "log_error": "2",
        "time_zone": ZONE,
    }

    report = files["report.md"].decode()
    assert report.startswith("# インシデントタイムライン 調査資料")
    assert re.findall(r"^## (.+)$", report, re.M) == [
        "条件",
        "メモ",
        "概要",
        "ハイライト",
        "注目すべき出来事",
    ]
    for fragment in (
        snapshot_id,
        "保存した結果",
        "2026/11/01 01:50:00 -04:00",
        "2026/11/01 01:10:00 -05:00",
        "サポートバンドル",
        "` demo-vcenter `",
        "` demo|esxi `",
        "対象（moid の無いイベント・ログの完全一致）",
        "` host-1 `",
        "min_score",
        "80",
        "85",
        "`````\n調査を引き継ぐ\n````\n![p](https://evil.example/p) @octocat\n`````",
        "表示した範囲の件数",
        "行数が上限",
        "最初の兆候",
        "影響の大きい対象",
        "demo-esxi-01",
        "初めて出た種別",
        "HostEvent",
        "検知した障害パターン",
        "接続の異常",
        "連続して発生",
        "総数: 2 件",
        "test-omitted",
        "総数 5 件のうち、表示した 1 件を ZIP の items.csv に入れた。報告書の表はそのうち 1 件",
    ):
        assert fragment in report
    assert "\u202e" not in report and "\x7f" not in report
    assert "75" not in report.split("## メモ")[0].split("CPU")[-1]

    md = await viewer_client.get(url, params={"format": "md"})
    assert md.status_code == 200
    assert md.headers["content-type"] == "text/markdown; charset=utf-8"
    assert re.fullmatch(
        rf'attachment; filename="timeline-\d{{8}}-\d{{6}}-{snapshot_id[:8]}\.md"',
        md.headers["content-disposition"],
    )
    assert (
        "総数 5 件のうち、表示した 1 件は ZIP の出力にある。報告書の表はそのうち 1 件"
        in md.text
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [None, {"from": "broken", "to": TO}])
async def test_unreadable_conditions_use_result_period(
    client: AsyncClient, saved: dict | None
) -> None:
    url = await _snapshot(_result(), view_request_payload=saved)
    response = await client.get(url, params={"format": "zip"})
    assert response.status_code == 200
    files = _archive(response.content)
    report = files["report.md"].decode()
    assert "2026/11/01 05:50:00 +00:00" in report.split("## 条件")[1]
    assert "保存した条件を読めません" in report
    assert "判定の無い結果" in report
    assert "全 0 件のうち 0 件。全件は ZIP の items.csv にある" in report
    assert json.loads(files["conditions.json"])["view_request"] == {
        **BODY,
        "detail": "保存した条件を読めません",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("item", "item-vc"),
        ("top", "top-vc"),
        ("pattern", "pattern-vc"),
        ("db", "db-vc"),
        ("id", str(VC)),
    ],
)
async def test_vcenter_name_order(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, candidate: str, expected: str
) -> None:
    async with session_scope() as session:
        session.add(
            VCenter(id=VC, name="db-vc", host="h", port=443, username="u", password="p")
        )
    items = (
        [_item(vcenter_id=str(VC), vcenter_name="item-vc")]
        if candidate == "item"
        else []
    )
    top = (
        [
            {
                "entity_name": "esxi",
                "item_count": 1,
                "first_seen_utc": FROM,
                "vcenter_id": str(VC),
                "vcenter_name": "top-vc",
            }
        ]
        if candidate in {"item", "top"}
        else []
    )
    patterns = (
        [
            {
                "pattern_id": "network",
                "title": "接続",
                "description": "",
                "level": "warning",
                "vcenter_id": str(VC),
                "vcenter_name": "pattern-vc",
                "entity_moid": "host-1",
                "first_utc": FROM,
                "last_utc": TO,
                "event_count": 1,
                "event_ids": [1],
            }
        ]
        if candidate not in {"id", "db"}
        else []
    )
    result = _result(
        items=items,
        total_items=len(items),
        highlights={"top_entities": top, "detected_patterns": patterns},
    )
    _aggregate_with(monkeypatch, result)
    request = {**BODY, "vcenter_id": str(VC)}
    if candidate == "id":
        url = await _snapshot(result, view_request_payload=request)
        response = await client.get(url, params={"format": "md"})
    else:
        response = await client.post(POST, params={"format": "md"}, json=request)
    assert response.status_code == 200
    assert f"- vCenter: ` {expected} `" in response.text


@pytest.mark.asyncio
async def test_notable_selection_preserves_input_order_and_log_quota(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    logs = [_item(i, id=f"log:{i}", kind="log", level="error") for i in range(1, 77)]
    events = [_item(i, score=i) for i in range(1, 26)]
    # 同時刻・同レベルなら、スコアの高いイベントよりアラートを先に選ぶ。
    alert = _item(1, id="alert:1", kind="alert", score=None)
    info = _item(999, level="info", score=100)
    _aggregate_with(
        monkeypatch, _result(items=[alert, *events, info, *logs], total_items=103)
    )
    response = await client.post(POST, params={"format": "md"}, json=BODY)
    assert response.status_code == 200
    assert "全 103 件のうち 100 件。全件は ZIP の出力にある" in response.text
    rows = response.text.split("## 注目すべき出来事")[1].splitlines()[6:]
    assert len(rows) == 100
    assert sum("| ログ |" in line for line in rows) == 75
    assert "| アラート |" in rows[0]
    assert "` 出来事 2 `" in rows[1]
    assert all("出来事 999" not in line for line in rows)
    assert "` 出来事 75 `" in rows[-1]


@pytest.mark.asyncio
async def test_notable_uses_recency_then_input_order_and_fills_with_info(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = [
        *[_item(i, level="critical") for i in range(1, 99)],
        _item(99, score=0),
        _item(100, score=0, timestamp_utc=TO),
        _item(101, score=0, timestamp_utc=TO),
        _item(102, score=0, timestamp_utc=TO),
        _item(103, level="info", score=100, timestamp_utc=TO),
    ]
    _aggregate_with(monkeypatch, _result(items=items, total_items=len(items)))
    response = await client.post(POST, params={"format": "md"}, json=BODY)
    table = response.text.split("## 注目すべき出来事")[1]
    assert "` 出来事 100 `" in table and "` 出来事 101 `" in table
    for index in (99, 102, 103):
        assert f"` 出来事 {index} `" not in table

    _aggregate_with(monkeypatch, _result(items=[items[0], items[-1]], total_items=2))
    response = await client.post(POST, params={"format": "md"}, json=BODY)
    assert "` 出来事 103 `" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("logs", "warnings", "infos", "expected_logs"),
    [
        (77, 0, 0, 77),
        (110, 10, 0, 90),
        (85, 15, 0, 85),
        (100, 0, 10, 100),
        (300, 10, 50, 90),
    ],
)
async def test_notable_follows_view_selection_for_each_level_group(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    logs: int,
    warnings: int,
    infos: int,
    expected_logs: int,
) -> None:
    # info を先に置き、補充した場合も表の順番が入力順に戻ることを確かめる。
    items = [
        *(_item(i, level="info") for i in range(infos)),
        *(_item(i) for i in range(infos, infos + warnings)),
        *(
            _item(i, kind="log", id=f"log:{i}", level="error")
            for i in range(infos + warnings, infos + warnings + logs)
        ),
    ]
    result = _result(items=items, total_items=len(items))
    entries = [
        TimelineEntry(
            source_id=index,
            kind=item.kind,
            timestamp_utc=item.timestamp_utc,
            level=item.level,
            title=item.title,
            score=item.score,
        )
        for index, item in enumerate(result.items)
    ]
    chosen, _ = select_within_limit(
        [entry for entry in entries if entry.level != "info"], 100, None
    )
    if len(chosen) < 100:
        fill, _ = select_within_limit(entries[:infos], 100 - len(chosen), None)
        chosen.extend(fill)
    expected_titles = [
        entry.title for entry in sorted(chosen, key=lambda entry: entry.source_id)
    ]

    _aggregate_with(monkeypatch, result)
    response = await client.post(POST, params={"format": "md"}, json=BODY)
    assert response.status_code == 200
    rows = response.text.split("## 注目すべき出来事")[1].splitlines()[6:]
    assert [row.split(" | ")[5] for row in rows] == [
        f"` {title} `" for title in expected_titles
    ]
    assert sum("| ログ |" in row for row in rows) == expected_logs
    assert len(rows) == min(len(items), 100)
    assert f"全 {len(items)} 件のうち {len(rows)} 件" in response.text


@pytest.mark.asyncio
async def test_bad_time_zone_rejected_before_aggregation_or_slot(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unexpected(*args, **kwargs):  # type: ignore[no-untyped-def]
        pytest.fail("不正なタイムゾーンで集計した")

    monkeypatch.setattr(routes, "build_incident_timeline_view", unexpected)
    settings = require_settings()
    with aggregation_slot("other", global_limit=1, per_owner_limit=1):
        monkeypatch.setattr(settings, "context_aggregation_concurrency", 1)
        for zone in ("Invalid/Zone", "../UTC", ""):
            response = await client.post(
                POST, params={"format": "md", "time_zone": zone}, json=BODY
            )
            assert response.status_code == 422
            assert "time_zone" in response.json()["detail"]
            assert (
                await client.get(
                    f"{MANUAL}/missing/export",
                    params={"format": "md", "time_zone": zone},
                )
            ).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, {"items": []}, "auto"])
async def test_missing_saved_result_returns_409(
    client: AsyncClient, payload: dict | str | None
) -> None:
    url = (
        (await _snapshot(snapshot_kind="auto"))
        if payload == "auto"
        else await _snapshot(payload)
    )
    response = await client.get(url, params={"format": "md"})
    assert response.status_code == 409
    assert response.headers["x-vea-error-code"] == "snapshot_result_missing"
    assert response.json()["detail"] == MISSING


@pytest.mark.asyncio
async def test_snapshot_not_found_and_formats(client: AsyncClient) -> None:
    for id_value in ("missing", str(uuid.uuid4())):
        assert (
            await client.get(f"{MANUAL}/{id_value}/export", params={"format": "md"})
        ).status_code == 404
    url = await _snapshot(_result())
    assert (await client.get(url, params={"format": "pdf"})).status_code == 422
    assert (
        await client.post(POST, params={"format": "pdf"}, json=BODY)
    ).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 422, 503])
async def test_live_aggregation_errors_pass_through(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    headers = {"Retry-After": "2"} if status == 503 else None

    async def failed(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise HTTPException(status, detail="集計エラー", headers=headers)

    monkeypatch.setattr(routes, "build_incident_timeline_view", failed)
    response = await client.post(POST, params={"format": "md"}, json=BODY)
    assert response.status_code == status
    assert response.json()["detail"] == "集計エラー"
    assert response.headers.get("retry-after") == ("2" if status == 503 else None)


@pytest.mark.asyncio
async def test_live_detail_cut_and_zip_size_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _item(detail="長" * 2100)
    _aggregate_with(
        monkeypatch,
        _result(items=[item], total_items=1, highlights={"first_signal": item}),
    )
    response = await client.post(POST, params={"format": "zip"}, json=BODY)
    files = _archive(response.content)
    result = json.loads(files["result.json"])
    expected = "長" * 2000 + "…（出力時に切り詰めました）"
    assert (
        result["items"][0]["detail"]
        == result["highlights"]["first_signal"]["detail"]
        == expected
    )
    assert (
        list(csv.DictReader(io.StringIO(files["items.csv"].decode("utf-8-sig"))))[0][
            "detail"
        ]
        == expected
    )

    _aggregate_with(
        monkeypatch,
        _result(items=[_item(title="X" * (8 * 1024 * 1024))], total_items=1),
    )
    response = await client.post(POST, params={"format": "zip"}, json=BODY)
    assert response.status_code == 413
    assert (
        response.json()["detail"]
        == "出力する結果が大きすぎます。期間を狭めるか、種別を減らしてください"
    )
    md = await client.post(POST, params={"format": "md"}, json=BODY)
    assert md.status_code == 200
    assert "## メモ" not in md.text
    assert "表示の後に集計し直したので、画面と件数が違うことがある" in md.text
    assert "` " + "X" * 200 + "… `" in md.text
    assert re.fullmatch(
        r'attachment; filename="timeline-\d{8}-\d{6}\.md"',
        md.headers["content-disposition"],
    )


@pytest.mark.asyncio
async def test_export_uses_aggregation_slots(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(require_settings(), "context_aggregation_concurrency", 1)
    url = await _snapshot(_result())
    with aggregation_slot("other", global_limit=1, per_owner_limit=1):
        invalid = await client.get(f"{MANUAL}/invalid/export", params={"format": "md"})
        assert invalid.status_code == 404
        saved = await client.get(url, params={"format": "md"})
        assert saved.status_code == 503 and saved.headers.get("retry-after")
        live = await client.post(POST, params={"format": "md"}, json=BODY)
        assert live.status_code == 503 and live.headers.get("retry-after")
        # 集計を置き換えても、生成自体の枠に空きがなければ 503 になる。
        _aggregate_with(monkeypatch, _result())
        live = await client.post(POST, params={"format": "md"}, json=BODY)
        assert live.status_code == 503 and live.headers.get("retry-after")
    assert (await client.get(url, params={"format": "md"})).status_code == 200


@pytest.mark.asyncio
async def test_cancelled_export_holds_slot_until_worker_exits(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(require_settings(), "context_aggregation_concurrency", 1)
    url = await _snapshot(_result())
    started = asyncio.Event()
    finish = Event()
    loop = asyncio.get_running_loop()
    main_thread = get_ident()
    original = routes._result_for_response

    def slow_read(
        row: IncidentTimelineManualSnapshot,
    ) -> IncidentTimelineViewResponse | None:
        assert get_ident() != main_thread
        loop.call_soon_threadsafe(started.set)
        assert finish.wait(timeout=5)
        return original(row)

    monkeypatch.setattr(routes, "_result_for_response", slow_read)
    request = asyncio.create_task(client.get(url, params={"format": "md"}))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        busy = await client.get(url, params={"format": "md"})
        assert busy.status_code == 503 and busy.headers.get("retry-after")
    finally:
        finish.set()

    async with asyncio.timeout(5):
        while (await client.get(url, params={"format": "md"})).status_code == 503:
            await asyncio.sleep(0.01)
    assert (await client.get(url, params={"format": "md"})).status_code == 200


@pytest.mark.asyncio
async def test_permissions_and_exporter_identity(
    open_client, anon_client: AsyncClient
) -> None:
    url = await _snapshot(_result())
    assert (await anon_client.get(url, params={"format": "md"})).status_code == 401
    assert (
        await anon_client.post(POST, params={"format": "md"}, json=BODY)
    ).status_code == 401
    name = "viewer-unique-export-account"
    async with open_client("viewer", username=name) as viewer:
        for response in (
            await viewer.get(url, params={"format": "zip"}),
            await viewer.post(POST, params={"format": "zip"}, json=BODY),
        ):
            assert response.status_code == 200
            assert all(
                name.encode() not in content
                for content in _archive(response.content).values()
            )


@pytest.mark.asyncio
async def test_csrf_requires_requested_with_header(make_login_cookie) -> None:
    name, token = await make_login_cookie("viewer")
    async with AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
        cookies={name: token},
    ) as client:
        response = await client.post(POST, params={"format": "md"}, json=BODY)
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_missing_header"


_MARKDOWN_CASES = [
    ("![p](https://evil.example/p.png)", "` ![p](https://evil.example/p.png) `"),
    ("[l](https://evil.example)", "` [l](https://evil.example) `"),
    (
        "<img src=https://evil.example/x.png>",
        "` <img src=https://evil.example/x.png> `",
    ),
    ("<script>alert(1)</script>", "` <script>alert(1)</script> `"),
    ("@octocat ping", "` @octocat ping `"),
    ("@github/security", "` @github/security `"),
    (
        "#1 and GH-1 and t-m0riyama/vcenter-event-assistant#1",
        "` #1 and GH-1 and t-m0riyama/vcenter-event-assistant#1 `",
    ),
    (
        "https://evil.example/auto www.evil.example",
        "` https://evil.example/auto www.evil.example `",
    ),
    ("# heading", "` # heading `"),
    ("> quote", "` > quote `"),
    ("- item", "` - item `"),
    ("a|b", "` a｜b `"),
    ("a\\|b", "` a\\｜b `"),
    ("a\\\\|b", "` a\\\\｜b `"),
    ("a\\\\\\|b", "` a\\\\\\｜b `"),
    ("trail\\", "` trail\\ `"),
    ("`start", "`` `start ``"),
    ("end`", "`` end` ``"),
    ("``double``", "``` ``double`` ```"),
    ("", "-"),
    ("   ", "-"),
    ("x\u202eevil\u202c y", "` xevil y `"),
    ("**bold** _em_ ~~strike~~", "` **bold** _em_ ~~strike~~ `"),
    ("&amp; &lt;b&gt;", "` &amp; &lt;b&gt; `"),
    (":+1: :smile:", "` :+1: :smile: `"),
    (
        "x\\|![p](https://evil.example/p.png) @octocat [l](https://evil.example)",
        "` x\\｜![p](https://evil.example/p.png) @octocat [l](https://evil.example) `",
    ),
    ("$x^2$ $$y$$", "` $x^2$ $$y$$ `"),
    ("[^1] footnote", "` [^1] footnote `"),
    ("A\r\nB\u2028C\u2029D\tE\x00\x85\u200b\u061c\ufeff", "` A  B C D E `"),
    ("A\u2060\U000e0001B", "` AB `"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("value", "expected"), _MARKDOWN_CASES)
async def test_markdown_prototype_cases(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, value: str, expected: str
) -> None:
    _aggregate_with(monkeypatch, _result(items=[_item(title=value)], total_items=1))
    response = await client.post(
        POST, params={"format": "md"}, json={**BODY, "entity": "a" * 301}
    )
    assert response.status_code == 200
    assert f"| {expected} |" in response.text
    assert "` " + "a" * 300 + "… `" in response.text


@pytest.mark.asyncio
async def test_export_time_zone_has_a_length_limit(client: AsyncClient) -> None:
    params = {"format": "md", "time_zone": "a" * 129}
    for response in (
        await client.post(POST, params=params, json=BODY),
        await client.get(f"{MANUAL}/{uuid.uuid4()}/export", params=params),
    ):
        assert response.status_code == 422
        (error,) = response.json()["detail"]
        assert error["loc"] == ["query", "time_zone"]
        assert error["type"] == "string_too_long"


@pytest.mark.asyncio
async def test_current_archive_conditions(client: AsyncClient) -> None:
    before = datetime.now(timezone.utc)
    response = await client.post(
        POST, params={"format": "zip", "time_zone": ZONE}, json=BODY
    )
    after = datetime.now(timezone.utc)
    assert response.status_code == 200
    conditions = json.loads(_archive(response.content)["conditions.json"])
    assert conditions["source"] == "current"
    assert conditions["time_zone"] == ZONE
    assert conditions["view_request"]["from"] == FROM
    assert conditions["view_request"]["to"] == TO
    assert "snapshot_id" not in conditions
    assert "operator_note" not in conditions
    assert (
        before
        <= datetime.fromisoformat(conditions["aggregated_at"])
        <= datetime.fromisoformat(conditions["exported_at"])
        <= after
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("value", "expected"), _MARKDOWN_CASES)
async def test_markdown_prototype_cases_outside_table(
    client: AsyncClient, value: str, expected: str
) -> None:
    result = _result(
        highlights={
            "first_signal": _item(entity_name=value, title=value, detail=value),
            "top_entities": [
                {
                    "vcenter_id": str(VC),
                    "vcenter_name": value,
                    "entity_name": value,
                    "item_count": 1,
                    "first_seen_utc": FROM,
                },
            ],
            "new_event_types": [
                {
                    "event_type": value,
                    "count": 1,
                    "first_seen_utc": FROM,
                    "max_score": 55,
                },
            ],
            "detected_patterns": [
                {
                    "pattern_id": "test-pattern",
                    "title": value,
                    "description": value,
                    "level": "warning",
                    "vcenter_id": str(VC),
                    "entity_moid": value,
                    "first_utc": FROM,
                    "last_utc": TO,
                    "event_count": 1,
                    "event_ids": [1],
                },
            ],
            "detected_patterns_total": 1,
            "omitted_patterns": [value],
        },
    )
    url = await _snapshot(
        result,
        view_request_payload={
            **BODY,
            "vcenter_id": str(VC),
            "entity": value,
            "entity_moid": value,
            "sources": [value],
        },
        operator_note=value,
    )
    response = await client.get(url, params={"format": "md"})
    assert response.status_code == 200
    report = response.text
    inline = expected.replace("｜", "|")
    vcenter = inline if value else f"` {VC} `"
    for fragment in (
        f"- vCenter: {vcenter}\n",
        f"- 対象（moid の無いイベント・ログの完全一致）: {inline}\n",
        f"- 対象の moid: {inline}\n",
        f"- 種別: {inline}\n",
        f"/ warning / {inline} / {inline} / {inline}\n",
        f"- {inline} / {inline} / 1 件 / ",
        f"- {inline} / 1 件 / ",
        f"- {inline} / {inline} / 2026/11/01 05:50:00 +00:00 ～ 2026/11/01 06:10:00 +00:00 / 1 件 / {inline}\n",
        f"- 判定を省いたパターン: {inline}\n",
    ):
        assert fragment in report

    # フェンスは行全体、コードスパンは同じ長さのバッククォートで閉じた箇所を取り除く。
    outside = re.sub(r"(?m)^(`{3,})\n[\s\S]*?^\1\n", "", report)
    outside = re.sub(r"(?<!`)(`+) [^\n]*? \1(?!`)", "", outside)
    for marker in ("<", "![", "](", "https://", "www.", "@octocat"):
        assert marker not in outside
    outside_lines = {line.strip() for line in outside.splitlines()}
    for line in value.splitlines():
        if re.match(r"^[#>-](?:\s|$)", line.strip()):
            assert line.strip() not in outside_lines
    assert "総数: 1 件" not in report


@pytest.mark.asyncio
async def test_markdown_note_strips_unicode_format_characters(
    client: AsyncClient,
) -> None:
    url = await _snapshot(
        _result(), operator_note="A\u200b\u2060\U000e0001B\r\n````\r\t> メモ"
    )
    response = await client.get(url, params={"format": "md"})
    assert response.status_code == 200
    assert "\n`````\nAB\n````\n\t> メモ\n`````\n" in response.text
