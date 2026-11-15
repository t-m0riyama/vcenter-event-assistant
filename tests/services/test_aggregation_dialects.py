"""Issue #301 の DB 側集計を SQLite と PostgreSQL の両方で確かめる。

PostgreSQL は ``VEA_TEST_POSTGRES_URL`` が専用のテスト DB を指すときだけ流す（スキーマを消す）。
CI には PostgreSQL がないので、方言ごとに compile した SQL の確認は SQLite のときも行う。
"""

from __future__ import annotations

import itertools
import os
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import asyncpg as pg_asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vcenter_event_assistant.db.base import Base
from vcenter_event_assistant.api.schemas.incident_timeline_view import IncidentTimelineViewRequest
from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    EventRecord,
    EventScoreRule,
    LogRecord,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.rules.notable import final_notable_score
from vcenter_event_assistant.services.chat.chat_event_time_buckets import build_chat_event_time_buckets
from vcenter_event_assistant.services.alerting.alert_eval_common import metric_context_key
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    METRIC_CPU,
    METRIC_MEM,
    build_chat_period_metrics,
)
from vcenter_event_assistant.services.incident_timeline_view import build_incident_timeline_view
from vcenter_event_assistant.services.metric_ranking import query_top_event_type_buckets

FROM = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
TO = FROM + timedelta(hours=2)
BUCKET = 15 * 60
_keys = itertools.count(1)


@pytest.fixture(params=["sqlite", "postgres"])
async def session(request, tmp_path) -> AsyncIterator[AsyncSession]:
    if request.param == "postgres":
        url = os.environ.get("VEA_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("VEA_TEST_POSTGRES_URL must point to a dedicated test DB (schema is cleared)")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'agg.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        if request.param == "postgres":
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            yield s
    finally:
        await engine.dispose()


async def _seed(session: AsyncSession) -> None:
    v1, v2 = uuid.uuid4(), uuid.uuid4()
    for vid in (v1, v2):
        session.add(VCenter(id=vid, name=f"vc-{vid.hex[:6]}", host="h", port=443, username="u", password="p"))
    session.add(EventScoreRule(event_type="CustomEvent", score_delta=7))
    await session.flush()

    def sample(vid: uuid.UUID, moid: str, key: str, at: datetime, value: float) -> MetricSample:
        return MetricSample(
            vcenter_id=vid,
            sampled_at=at,
            entity_type="HostSystem",
            entity_moid=moid,
            entity_name=moid.upper(),
            metric_key=key,
            value=value,
        )

    # 境界の直前（秒未満あり）・境界ちょうど・to ちょうど・vCenter をまたぐ同じ moid
    session.add_all(
        [
            sample(v1, "h1", METRIC_CPU, FROM, 10.0),
            sample(v1, "h1", METRIC_CPU, FROM + timedelta(minutes=14, seconds=59, microseconds=999_600), 30.0),
            sample(v2, "h1", METRIC_CPU, FROM + timedelta(minutes=15), 70.0),
            sample(v1, "h1", METRIC_CPU, TO, 99.0),
            sample(v1, "h2", METRIC_CPU, FROM + timedelta(minutes=1), 50.0),
            sample(v1, "h3", METRIC_CPU, FROM + timedelta(minutes=1), 5.0),
            sample(v1, "h3", METRIC_MEM, FROM + timedelta(minutes=1), 90.0),
        ]
    )
    rows = [
        (FROM + timedelta(minutes=14, seconds=59, microseconds=999_600), "HostConnectionLostEvent", "info", "LOST", 0),
        (FROM + timedelta(minutes=15), "HostConnectionLostEvent", "warning", "ok", 0),
        (FROM + timedelta(minutes=16), "CustomEvent", "Error", "Disk Corrupt", 0),
        (FROM + timedelta(minutes=17), "CustomEvent", None, "", 0),
        (TO, "CustomEvent", "error", "fail", 0),
    ]
    for at, et, sev, msg, score in rows:
        session.add(
            EventRecord(
                vcenter_id=v1,
                occurred_at=at,
                event_type=et,
                severity=sev,
                message=msg,
                vmware_key=next(_keys),
                notable_score=score,
            )
        )
    await session.flush()


@pytest.mark.asyncio
async def test_period_metrics_on_each_dialect(session: AsyncSession) -> None:
    await _seed(session)
    out = await build_chat_period_metrics(
        session,
        FROM,
        TO,
        vcenter_id=None,
        include_cpu=True,
        include_memory=True,
        include_disk_io=False,
        include_network_io=False,
        bucket_sec=BUCKET,
        max_hosts_per_category=2,
    )
    assert out is not None and out.cpu is not None and out.memory is not None
    # h1 のピークは 70、h2 は 50、h3 は 5 → 上位 2 台は h1・h2
    assert sorted(s.entity_moid for s in out.cpu) == ["h1", "h2"]
    h1 = next(s for s in out.cpu if s.entity_moid == "h1")
    assert h1.entity_name == "H1"
    assert [p.bucket_start_utc for p in h1.series] == [FROM, FROM + timedelta(minutes=15)]
    assert h1.series[0].avg == pytest.approx(20.0)
    assert h1.series[0].n == 2
    assert h1.series[1].avg == pytest.approx(70.0)
    assert [s.entity_moid for s in out.memory] == ["h3"]


@pytest.mark.asyncio
async def test_event_buckets_on_each_dialect(session: AsyncSession) -> None:
    await _seed(session)
    out = await build_chat_event_time_buckets(session, FROM, TO, vcenter_id=None, bucket_sec=BUCKET)
    assert [b.bucket_start_utc for b in out.buckets] == [FROM, FROM + timedelta(minutes=15)]
    assert out.buckets[0].by_type == {"HostConnectionLostEvent": 1}
    assert out.buckets[1].by_type == {"CustomEvent": 2, "HostConnectionLostEvent": 1}


@pytest.mark.asyncio
async def test_top_event_type_scores_on_each_dialect(session: AsyncSession) -> None:
    await _seed(session)
    got = await query_top_event_type_buckets(
        session, [EventRecord.occurred_at >= FROM, EventRecord.occurred_at < TO]
    )
    expected = {
        "HostConnectionLostEvent": max(
            final_notable_score(event_type="HostConnectionLostEvent", severity="info", message="LOST"),
            final_notable_score(event_type="HostConnectionLostEvent", severity="warning", message="ok"),
        ),
        "CustomEvent": max(
            final_notable_score(event_type="CustomEvent", severity="Error", message="Disk Corrupt", score_delta=7),
            final_notable_score(event_type="CustomEvent", severity=None, message="", score_delta=7),
        ),
    }
    assert {b.event_type: b.max_notable_score for b in got} == expected


@pytest.mark.asyncio
async def test_group_by_has_no_bind_parameters_on_postgres(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PostgreSQL では GROUP BY の式にバインドパラメータがあると、SELECT 側と別番号になって失敗する。

    集計の SQL を asyncpg の方言で compile し、GROUP BY 句が列の参照だけであることを確かめる。
    """
    await _seed(session)
    captured: list[object] = []
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(statement)
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", spy)
    await build_chat_period_metrics(
        session,
        FROM,
        TO,
        vcenter_id=None,
        include_cpu=True,
        include_memory=True,
        include_disk_io=True,
        include_network_io=True,
        bucket_sec=BUCKET,
    )
    await build_chat_event_time_buckets(session, FROM, TO, vcenter_id=None, bucket_sec=BUCKET, max_rows=10)
    await query_top_event_type_buckets(session, [EventRecord.occurred_at >= FROM])
    await build_incident_timeline_view(
        session, IncidentTimelineViewRequest(from_time=FROM, to_time=TO), owner_key="dialect-test"
    )

    compiled = "\n".join(
        str(stmt.compile(dialect=pg_asyncpg.dialect()))  # type: ignore[attr-defined]
        for stmt in captured
    )
    # 集計の GROUP BY は、副問い合わせの列の参照だけになっている（バインドパラメータを含まない）。
    for expected in (
        "GROUP BY base.cat, base.moid, base.mk, base.bidx",
        "GROUP BY base.bidx, base.event_type",
        "GROUP BY score_inputs.event_type, score_inputs.severity, score_inputs.has_keyword",
        "GROUP BY base.bidx\n",
        "GROUP BY log_base.bidx",
        "GROUP BY metric_in_period.vc, metric_in_period.moid, metric_in_period.mk, metric_in_period.run",
    ):
        assert expected in compiled, expected
    for m in re.finditer(r"GROUP BY ([^\n]+)", compiled):
        assert "$" not in m.group(1), m.group(1)


@pytest.mark.asyncio
async def test_event_rate_series_on_each_dialect(session: AsyncSession) -> None:
    """エポック秒の式を共通化した ``get_event_rate_series`` も両方の方言で動く（BIGINT への CAST）。"""
    from vcenter_event_assistant.services.event_repository import get_event_rate_series

    await _seed(session)
    series = await get_event_rate_series(session, "CustomEvent", FROM, TO - timedelta(seconds=1), BUCKET)
    counts = {b["bucket_start"]: b["count"] for b in series}
    assert counts[FROM + timedelta(minutes=15)] == 2
    assert sum(counts.values()) == 2


@pytest.mark.asyncio
async def test_incident_timeline_view_on_each_dialect(session: AsyncSession) -> None:
    """タイムライン表示の俯瞰（GROUP BY）、直前の期間の種別、アラートの対象解決（MAX + JOIN）。"""
    await _seed(session)
    vid = (await session.execute(text("SELECT vcenter_id FROM events LIMIT 1"))).scalar_one()
    vid = vid if isinstance(vid, uuid.UUID) else uuid.UUID(str(vid))
    other = next(v for v in (await session.execute(select(VCenter.id))).scalars() if v != vid)
    # v2 の h1 にだけ別名のサンプルを、両方のアラート（20 分・21 分）より前に足す。
    # vCenter をまたいで取り違えると v1 の名前が変わる
    session.add(
        MetricSample(
            vcenter_id=other,
            sampled_at=FROM + timedelta(minutes=18),
            entity_type="HostSystem",
            entity_moid="h1",
            entity_name="H1-ON-V2",
            metric_key=METRIC_CPU,
            value=1.0,
        )
    )
    rule = AlertRule(name="cpu", rule_type="metric_threshold", alert_level="critical", config={"metric_key": METRIC_CPU})
    session.add(rule)
    await session.flush()
    for minute, vcenter in ((20, vid), (21, other)):
        session.add(
            AlertHistory(
                rule_id=rule.id,
                alert_level="critical",
                state="firing",
                context_key=metric_context_key(vcenter, "h1"),
                notified_at=FROM + timedelta(minutes=minute),
                channel="none",
            )
        )
    session.add(
        EventRecord(
            vcenter_id=vid,
            occurred_at=FROM - timedelta(minutes=30),
            event_type="HostConnectionLostEvent",
            message="",
            vmware_key=next(_keys),
            notable_score=0,
        )
    )
    await session.flush()

    out = await build_incident_timeline_view(
        session,
        IncidentTimelineViewRequest(from_time=FROM, to_time=TO, min_score=0),
        owner_key="dialect-test",
    )
    assert out.bucket_seconds == 60
    assert len(out.overview) == 120
    # 期間内のイベントは 4 件（TO ちょうどは含まない）。14:59.9996 は秒に切り捨てて 14 分のバケット
    totals = {b.bucket_start_utc: b.event_total for b in out.overview if b.event_total}
    assert totals == {
        FROM + timedelta(minutes=14): 1,
        FROM + timedelta(minutes=15): 1,
        FROM + timedelta(minutes=16): 1,
        FROM + timedelta(minutes=17): 1,
    }
    assert sum(b.event_notable for b in out.overview) == 4
    assert sum(b.alert for b in out.overview) == 2
    alerts = [i for i in out.items if i.kind == "alert"]
    # context_key の vCenter ごとに、アラートの時刻までで最も新しい CPU のサンプルの名前で解決する
    assert [(a.vcenter_id, a.entity_name) for a in alerts] == [(vid, "H1"), (other, "H1-ON-V2")]
    assert alerts[0].ref.metric_key == METRIC_CPU
    # HostConnectionLostEvent は直前の期間にある（スコア 0）ので新しい種別ではない
    assert [n.event_type for n in out.highlights.new_event_types] == ["CustomEvent"]


@pytest.mark.asyncio
async def test_metric_entities_at_alert_times_on_each_dialect(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """アラートの時刻ごとの対象名の解決（VALUES の CTE + 相関副問い合わせ）を両方の方言で確かめる。

    - 組が 500 件を超えると 2 本に分かれる（問い合わせの本数は組 500 件ごとに 1 本）
    - ``sampled_at == occurred_at`` のサンプルを使い、1 マイクロ秒後のサンプルは使わない
    - さかのぼる下限（``occurred_at - lookback``）は含む
    - 別の vCenter の同じ moid と混ざらない
    - ``metric_keys`` を渡すとその指標だけを見て、None なら指標で絞らない
    """
    from vcenter_event_assistant.services.alerting.alert_entity_resolution import resolve_metric_entities_at

    v1, v2 = uuid.uuid4(), uuid.uuid4()
    for vid in (v1, v2):
        session.add(VCenter(id=vid, name=f"vc-{vid.hex[:6]}", host="h", port=443, username="u", password="p"))
    await session.flush()
    lookback = timedelta(hours=6)
    base = FROM + timedelta(microseconds=123_456)

    def sample(vid: uuid.UUID, moid: str, at: datetime, name: str, key: str = METRIC_CPU) -> MetricSample:
        return MetricSample(
            vcenter_id=vid, sampled_at=at, entity_type="VirtualMachine", entity_moid=moid,
            entity_name=name, metric_key=key, value=1.0,
        )

    probes: set[tuple[uuid.UUID, str, datetime]] = set()
    rows: list[MetricSample] = []
    for i in range(501):
        at = base + timedelta(seconds=i)
        rows.append(sample(v1, f"vm-{i}", at, f"N{i}"))
        rows.append(sample(v1, f"vm-{i}", at + timedelta(microseconds=1), f"later-{i}"))
        probes.add((v1, f"vm-{i}", at))
    rows.append(sample(v2, "vm-0", base, "ON-V2"))
    probes.add((v2, "vm-0", base))
    rows.append(sample(v1, "vm-mem", base - timedelta(minutes=10), "cpu-name"))
    rows.append(sample(v1, "vm-mem", base - timedelta(minutes=1), "mem-name", METRIC_MEM))
    probes.add((v1, "vm-mem", base))
    rows.append(sample(v1, "vm-edge-in", base - lookback, "edge-in"))
    rows.append(sample(v1, "vm-edge-out", base - lookback - timedelta(microseconds=1), "edge-out"))
    probes |= {(v1, "vm-edge-in", base), (v1, "vm-edge-out", base)}
    session.add_all(rows)
    await session.flush()

    calls = 0
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", spy)
    got = await resolve_metric_entities_at(session, probes, {METRIC_CPU}, lookback=lookback)
    monkeypatch.setattr(AsyncSession, "execute", original)

    assert calls == 2  # 505 組 → 500 件ごとに 1 本
    assert all(got[(v1, f"vm-{i}", base + timedelta(seconds=i))].name == f"N{i}" for i in range(501))
    assert got[(v1, "vm-0", base)].entity_type == "VirtualMachine"
    assert got[(v2, "vm-0", base)].name == "ON-V2"
    assert got[(v1, "vm-mem", base)].name == "cpu-name"
    assert got[(v1, "vm-edge-in", base)].name == "edge-in"
    assert (v1, "vm-edge-out", base) not in got
    assert len(got) == 504

    unfiltered = await resolve_metric_entities_at(session, {(v1, "vm-mem", base)}, None, lookback=lookback)
    assert unfiltered[(v1, "vm-mem", base)].name == "mem-name"


@pytest.mark.asyncio
async def test_incident_timeline_metric_intervals_on_each_dialect(session: AsyncSession) -> None:
    """超過区間の window 関数（LAG・累積和・FIRST_VALUE）と GROUP BY が両方の方言で同じ結果になる。

    - 閾値ちょうどは超過、閾値未満のサンプルで区切る
    - 間隔は秒に切り捨てて比べ、上限（既定 15 分）ちょうどはつなぐ
    - 期間の開始前から続く区間は、期間内のサンプルだけで開始・ピーク・件数を決める
    - 別の vCenter の同じ moid と混ざらない。名前は空でない最新のもの
    """
    v1, v2 = uuid.uuid4(), uuid.uuid4()
    for vid, name in ((v1, "vc-one"), (v2, "vc-two")):
        session.add(VCenter(id=vid, name=name, host="h", port=443, username="u", password="p"))
    await session.flush()

    def at(minute: float, micro: int = 0) -> datetime:
        return FROM + timedelta(minutes=minute, microseconds=micro)

    def sample(vid: uuid.UUID, moid: str, when: datetime, value: float, *, key: str = METRIC_CPU, name: str = "") -> MetricSample:
        return MetricSample(
            vcenter_id=vid, sampled_at=when, entity_type="HostSystem", entity_moid=moid,
            entity_name=name or moid.upper(), metric_key=key, value=value,
        )

    session.add_all(
        [
            # h1 (v1): 期間の前から継続 → 10 分で閾値未満 → 15 分から再び超過（15 分ちょうどの欠けはつなぐ）
            sample(v1, "h1", at(-5), 99.0),
            sample(v1, "h1", at(0, 900_000), 85.0),
            sample(v1, "h1", at(5), 92.0, name="  "),
            sample(v1, "h1", at(10), 79.99),
            sample(v1, "h1", at(15), 80.0, name="H1-RENAMED"),
            sample(v1, "h1", at(30, 100_000), 81.0, name="  "),
            # 16 分空く → 別の区間
            sample(v1, "h1", at(46, 200_000), 83.0),
            # h1 (v2): 同じ moid。v1 の区間につながらない
            sample(v2, "h1", at(12), 90.0, name="H1-ON-V2"),
            # h3 (v1): メモリ。閾値 85 未満は出ない、TO ちょうどは期間外
            sample(v1, "h3", at(20), 84.0, key=METRIC_MEM),
            sample(v1, "h3", at(25), 97.0, key=METRIC_MEM),
            sample(v1, "h3", TO, 99.0, key=METRIC_MEM),
            # ディスクの KB/s は対象外
            sample(v1, "h3", at(25), 5000.0, key="host.disk.usage_pct"),
        ]
    )
    await session.flush()

    out = await build_incident_timeline_view(
        session,
        IncidentTimelineViewRequest(from_time=FROM, to_time=TO, sources=["metric"]),
        owner_key="dialect-test",
    )
    got = [
        (i.vcenter_name, i.ref.entity_moid, i.ref.metric_key, i.timestamp_utc, i.end_utc, i.entity_name, i.level, i.detail)
        for i in out.items
    ]
    assert got == [
        ("vc-one", "h1", METRIC_CPU, at(0, 900_000), at(5), "H1", "warning",
         "ピーク 92%（2026-03-22 00:05:00 UTC）、サンプル 2 件、期間の開始前から継続"),
        ("vc-two", "h1", METRIC_CPU, at(12), None, "H1-ON-V2", "warning",
         "ピーク 90%（2026-03-22 00:12:00 UTC）、サンプル 1 件"),
        ("vc-one", "h1", METRIC_CPU, at(15), at(30, 100_000), "H1-RENAMED", "warning",
         "ピーク 81%（2026-03-22 00:30:00 UTC）、サンプル 2 件"),
        ("vc-one", "h3", METRIC_MEM, at(25), None, "H3", "error",
         "ピーク 97%（2026-03-22 00:25:00 UTC）、サンプル 1 件"),
        ("vc-one", "h1", METRIC_CPU, at(46, 200_000), None, "H1", "warning",
         "ピーク 83%（2026-03-22 00:46:00 UTC）、サンプル 1 件"),
    ]
    breach = [b.metric_breach for b in out.overview]
    assert breach[:7] == [1, 1, 1, 1, 1, 1, 0]
    assert sum(breach) == 6 + 1 + 16 + 1 + 1


@pytest.mark.asyncio
async def test_incident_timeline_logs_on_each_dialect(session: AsyncSession) -> None:
    """ログの重大度の正規化（lower / trim）、effective_at のバケット、message の先頭の切り出し（文字数）。"""
    v1, v2 = uuid.uuid4(), uuid.uuid4()
    for vid in (v1, v2):
        session.add(VCenter(id=vid, name=f"vc-{vid.hex[:6]}", host="h", port=443, username="u", password="p"))
    await session.flush()
    offsets = itertools.count(1)

    def log(vid: uuid.UUID, when: datetime, severity: str | None, message: str, *, host: str = "esx01", kind: str = "vmkernel") -> LogRecord:
        return LogRecord(
            vcenter_id=vid, collector_id="c", source_id="s", host=host, log_kind=kind,
            file_generation="g", byte_offset=next(offsets), occurred_at=None,
            collected_at=when, effective_at=when, severity=severity, message=message,
        )

    long_jp = "障" * 1200
    session.add_all(
        [
            log(v1, FROM + timedelta(minutes=14, seconds=59, microseconds=999_600), "ERROR", long_jp),
            log(v1, FROM + timedelta(minutes=15), " Critical ", "second"),
            log(v1, FROM + timedelta(minutes=16), "warning", "skip"),
            log(v1, FROM + timedelta(minutes=17), None, "skip"),
            log(v1, FROM + timedelta(minutes=18), "panic", "other host", host="ESX02.example.com"),
            log(v2, FROM + timedelta(minutes=19), "error", "other vcenter"),
            log(v1, TO, "error", "at to"),
        ]
    )
    await session.flush()

    out = await build_incident_timeline_view(
        session,
        IncidentTimelineViewRequest(from_time=FROM, to_time=TO, sources=["log"], vcenter_id=v1),
        owner_key="dialect-test",
    )
    # "ERROR" は warning、" Critical " は error なので別の行になる
    assert [(i.title, i.count, i.level, i.timestamp_utc) for i in out.items] == [
        ("esx01 vmkernel", 1, "warning", FROM + timedelta(minutes=14, seconds=59, microseconds=999_600)),
        ("esx01 vmkernel", 1, "error", FROM + timedelta(minutes=15)),
        ("ESX02.example.com vmkernel", 1, "error", FROM + timedelta(minutes=18)),
    ]
    assert out.items[0].detail == "障" * 1000 + "…"
    counts = {b.bucket_start_utc: b.log_error for b in out.overview if b.log_error}
    assert counts == {
        FROM + timedelta(minutes=14): 1,
        FROM + timedelta(minutes=15): 1,
        FROM + timedelta(minutes=18): 1,
    }

    filtered = await build_incident_timeline_view(
        session,
        IncidentTimelineViewRequest(from_time=FROM, to_time=TO, sources=["log"], entity="esx02"),
        owner_key="dialect-test",
    )
    assert [i.detail for i in filtered.items] == ["other host"]
