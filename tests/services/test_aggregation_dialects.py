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
        "GROUP BY metric_run_stats.vc, metric_run_stats.moid, metric_run_stats.mk, metric_run_stats.run",
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

    組は (vcenter_id, moid, そのルールの metric_key, occurred_at)。

    - 指標のある組が 500 件を超えると 2 本に分かれ、指標の無い組は別の 1 本になる
    - ``sampled_at == occurred_at`` のサンプルを使い、1 マイクロ秒後のサンプルは使わない
    - さかのぼる下限（``occurred_at - lookback``）は含む
    - 別の vCenter の同じ moid と混ざらない
    - 各組は自分の指標だけを見る。同じ呼び出しに同じ対象・同じ時刻の別の指標の組があっても影響しない
    - 指標が None の組だけは指標で絞らず、全指標から最も新しいサンプルを使う
    """
    from vcenter_event_assistant.services.alerting.alert_entity_resolution import resolve_metric_entities_at

    v1, v2 = uuid.uuid4(), uuid.uuid4()
    for vid in (v1, v2):
        session.add(VCenter(id=vid, name=f"vc-{vid.hex[:6]}", host="h", port=443, username="u", password="p"))
    await session.flush()
    lookback = timedelta(hours=6)
    base = FROM + timedelta(microseconds=123_456)
    cpu, mem = METRIC_CPU, METRIC_MEM

    def sample(vid: uuid.UUID, moid: str, at: datetime, name: str, key: str = cpu) -> MetricSample:
        return MetricSample(
            vcenter_id=vid, sampled_at=at, entity_type="VirtualMachine", entity_moid=moid,
            entity_name=name, metric_key=key, value=1.0,
        )

    probes: set[tuple[uuid.UUID, str, str | None, datetime]] = set()
    rows: list[MetricSample] = []
    for i in range(501):
        at = base + timedelta(seconds=i)
        rows.append(sample(v1, f"vm-{i}", at, f"N{i}"))
        rows.append(sample(v1, f"vm-{i}", at + timedelta(microseconds=1), f"later-{i}"))
        probes.add((v1, f"vm-{i}", cpu, at))
    rows.append(sample(v2, "vm-0", base, "ON-V2"))
    probes.add((v2, "vm-0", cpu, base))
    # 同じ対象・同じ時刻で、CPU は改名前、メモリは改名後の名前が最新
    rows.append(sample(v1, "vm-mem", base - timedelta(minutes=10), "cpu-name"))
    rows.append(sample(v1, "vm-mem", base - timedelta(minutes=1), "mem-name", mem))
    probes |= {(v1, "vm-mem", cpu, base), (v1, "vm-mem", mem, base), (v1, "vm-mem", None, base)}
    rows.append(sample(v1, "vm-edge-in", base - lookback, "edge-in"))
    rows.append(sample(v1, "vm-edge-out", base - lookback - timedelta(microseconds=1), "edge-out"))
    probes |= {(v1, "vm-edge-in", cpu, base), (v1, "vm-edge-out", cpu, base)}
    session.add_all(rows)
    await session.flush()

    calls = 0
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", spy)
    got = await resolve_metric_entities_at(session, probes, lookback=lookback)
    monkeypatch.setattr(AsyncSession, "execute", original)

    assert calls == 3  # 指標のある 506 組 → 2 本、指標の無い 1 組 → 1 本
    assert all(got[(v1, f"vm-{i}", cpu, base + timedelta(seconds=i))].name == f"N{i}" for i in range(501))
    assert got[(v1, "vm-0", cpu, base)].entity_type == "VirtualMachine"
    assert got[(v2, "vm-0", cpu, base)].name == "ON-V2"
    assert got[(v1, "vm-mem", cpu, base)].name == "cpu-name"
    assert got[(v1, "vm-mem", mem, base)].name == "mem-name"
    assert got[(v1, "vm-mem", None, base)].name == "mem-name"
    assert got[(v1, "vm-edge-in", cpu, base)].name == "edge-in"
    assert (v1, "vm-edge-out", cpu, base) not in got
    assert len(got) == 506

    # 単独で引いても、ほかの組と一緒に引いたときと同じ結果になる
    for probe in ((v1, "vm-mem", cpu, base), (v1, "vm-mem", mem, base), (v1, "vm-0", cpu, base)):
        alone = await resolve_metric_entities_at(session, {probe}, lookback=lookback)
        assert alone == {probe: got[probe]}


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
            sample(v1, "h3", at(25), 5000.0, key="host.disk.usage_kbps"),
            # h6 (v2): 名前が空白だけ → 名前は moid。期間の終わりの 20 分前で途絶える → 終わりでは続いていない
            sample(v2, "h6", at(100), 90.0, name="   "),
            # h4 (v1): 期間の終わりの 1.5 分前まで超過 → 終わりでも継続
            sample(v1, "h4", at(110), 90.0),
            sample(v1, "h4", at(118, 500_000), 91.0),
            # h5 (v1): 期間の終わりの手前で閾値未満に下がる → 終わりでは続いていない
            sample(v1, "h5", at(112), 90.0),
            sample(v1, "h5", at(117), 50.0),
        ]
    )
    await session.flush()

    out = await build_incident_timeline_view(
        session,
        IncidentTimelineViewRequest(from_time=FROM, to_time=TO, sources=["metric"]),
        owner_key="dialect-test",
    )
    got = [
        (i.vcenter_name, i.ref.entity_moid, i.ref.metric_key, i.timestamp_utc, i.end_utc, i.entity_name, i.level,
         i.ref.peak_value, i.ref.peak_at_utc, i.ref.sample_count, i.ref.continues_from_before, i.ref.threshold_pct,
         i.ref.continues_after)
        for i in out.items
    ]
    assert got == [
        ("vc-one", "h1", METRIC_CPU, at(0, 900_000), at(5), "H1", "warning", 92.0, at(5), 2, True, 80.0, False),
        ("vc-two", "h1", METRIC_CPU, at(12), None, "H1-ON-V2", "warning", 90.0, at(12), 1, False, 80.0, False),
        ("vc-one", "h1", METRIC_CPU, at(15), at(30, 100_000), "H1-RENAMED", "warning", 81.0, at(30, 100_000), 2, False, 80.0, False),
        ("vc-one", "h3", METRIC_MEM, at(25), None, "H3", "error", 97.0, at(25), 1, False, 85.0, False),
        ("vc-one", "h1", METRIC_CPU, at(46, 200_000), None, "H1", "warning", 83.0, at(46, 200_000), 1, False, 80.0, False),
        ("vc-two", "h6", METRIC_CPU, at(100), None, "h6", "warning", 90.0, at(100), 1, False, 80.0, False),
        ("vc-one", "h4", METRIC_CPU, at(110), at(118, 500_000), "H4", "warning", 91.0, at(118, 500_000), 2, False, 80.0, True),
        ("vc-one", "h5", METRIC_CPU, at(112), None, "H5", "warning", 90.0, at(112), 1, False, 80.0, False),
    ]
    assert out.items[0].detail == "ピーク 92%、サンプル 2 件、期間の開始前から継続"
    assert out.items[6].detail == "ピーク 91%、サンプル 2 件、期間の終わりでも継続"
    breach = [b.metric_breach for b in out.overview]
    assert breach[:7] == [1, 1, 1, 1, 1, 1, 0]
    assert sum(breach) == 6 + 1 + 16 + 1 + 1 + 1 + 9 + 1

    # 名前が空の系列は moid で表示し、その moid で絞っても消えない（coalesce(名前, moid) に当てる）
    by_moid = await build_incident_timeline_view(
        session,
        IncidentTimelineViewRequest(from_time=FROM, to_time=TO, sources=["metric"], entity="h6"),
        owner_key="dialect-test",
    )
    assert [(i.ref.entity_moid, i.entity_name) for i in by_moid.items] == [("h6", "h6")]


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



@pytest.mark.asyncio
async def test_sqlite_timeline_queries_use_the_timeline_indexes(session: AsyncSession) -> None:
    """SQLite の計画で、メトリクスとエラーログの問い合わせがタイムライン用の索引を使う（vCenter の指定の有無とも）。

    SQLite は並べ替えを省ける索引を好むので、問い合わせの形（PARTITION BY の列の順、ログの一覧の ORDER BY を
    付けないこと）を戻すと、期間内の全行を読む計画に戻る。その退行を見張る。
    """
    if session.get_bind().dialect.name != "sqlite":
        pytest.skip("SQLite の計画の確認")
    from vcenter_event_assistant.services import incident_timeline_view as itv

    vid = uuid.uuid4()
    session.add(VCenter(id=vid, name="vc-plan", host="h", port=443, username="u", password="p"))
    await session.flush()
    plans: list[str] = []
    for vc in (None, vid):
        scope = itv._Scope(
            from_utc=FROM, to_utc=TO, vcenter_id=vc, entity=None, min_score=1, bucket_sec=60,
            bucket_count=120, max_rows=10, dialect_name="sqlite", metric_name_lookback=timedelta(hours=6),
            metric_thresholds=((METRIC_CPU, 80.0), (METRIC_MEM, 85.0)),
        )
        captured: list = []
        original = AsyncSession.execute

        async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
            captured.append(statement)
            return await original(self, statement, *args, **kwargs)

        AsyncSession.execute = spy  # type: ignore[method-assign]
        try:
            await itv._collect_metrics(session, scope)
            await itv._collect_logs(session, scope)
        finally:
            AsyncSession.execute = original  # type: ignore[method-assign]
        bind = session.get_bind()
        for stmt in captured:
            sql = str(stmt.compile(dialect=bind.dialect, compile_kwargs={"literal_binds": True}))
            # SQLite の OFFSET に付く LIMIT -1 は literal_binds でもバインド変数のまま残る
            sql = sql.replace("LIMIT ? OFFSET", "LIMIT -1 OFFSET")
            if "metric_intervals" not in sql and "FROM log_records" not in sql:
                continue
            conn = await session.connection()
            rows = (await conn.exec_driver_sql("EXPLAIN QUERY PLAN " + sql)).all()
            plan = "\n".join(str(r[-1]) for r in rows)
            plans.append(plan)
            if "metric_intervals" in sql:
                assert "SEARCH metric_samples USING INDEX ix_metric_samples_vcenter_metric_sampled_value" in plan, plan
            else:
                expected = (
                    "ix_log_records_vcenter_severity_norm_effective" if vc else "ix_log_records_severity_norm_effective"
                )
                # 新しい SQLite（3.51.0 以降で確認）は、同じ索引を式の索引でも被覆として扱い COVERING INDEX と出す
                assert re.search(rf"SEARCH log_records USING (COVERING )?INDEX {expected} ", plan), plan
    assert len(plans) == 6  # メトリクス 1 本 + ログ 2 本（俯瞰と一覧）× vCenter の指定なし・あり


@pytest.mark.asyncio
@pytest.mark.parametrize("entity", [None, "esx"], ids=["no_entity", "entity"])
async def test_sqlite_timeline_metric_queries_pin_the_covering_index(session: AsyncSession, entity: str | None) -> None:
    """閾値以上のサンプル数の上限を指定したタイムラインで（対象 entity の指定の有無とも）、metric_samples を読む
    select がすべて INDEXED BY で被覆索引に固定され、vCenter・指標・期間の範囲を読む（Issue #334）。

    - 対象に当たる系列（matching_series）は、系列の索引 (vcenter_id=?) でその vCenter の全履歴を読まない。
    - 上限の数え上げ（capped）と区間の問い合わせ（hits0）も、同じ索引で期間を絞る。
    - 直前のサンプル（metric_prev）と間のサンプル（metric_between）は別名なので、固定しない。

    古い SQLite（3.47.1 など）はヒントが無くても同じ計画を選ぶことがあるので、ヒントがあることは SQL の文字列で、
    計画が想定どおりかは計画で確かめる。
    """
    if session.get_bind().dialect.name != "sqlite":
        pytest.skip("SQLite の計画の確認")
    from vcenter_event_assistant.services import incident_timeline_view as itv

    vid = uuid.uuid4()
    # vCenter を指定しないときに IN の要素が 2 つ以上になるよう、2 つ登録する
    for v, name in ((vid, "vc-plan"), (uuid.uuid4(), "vc-plan-2")):
        session.add(VCenter(id=v, name=name, host="h", port=443, username="u", password="p"))
    await session.flush()
    covering_range = (
        "COVERING INDEX ix_metric_samples_vcenter_metric_sampled_value "
        "(vcenter_id=? AND metric_key=? AND sampled_at>? AND sampled_at<?)"
    )
    hint = "metric_samples INDEXED BY ix_metric_samples_vcenter_metric_sampled_value"
    # capped と hits0 に 1 つずつ、対象を指定したときは IN の副問い合わせ（matching_series）にもう 1 つ
    expected_reads = 2 if entity else 1
    for vc in (None, vid):
        scope = itv._Scope(
            from_utc=FROM, to_utc=TO, vcenter_id=vc, entity=entity, min_score=1, bucket_sec=60,
            bucket_count=120, max_rows=10, dialect_name="sqlite", metric_name_lookback=timedelta(hours=6),
            metric_thresholds=((METRIC_CPU, 80.0), (METRIC_MEM, 85.0)), metric_breach_sample_limit=1000,
        )
        captured: list = []
        original = AsyncSession.execute

        async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
            captured.append(statement)
            return await original(self, statement, *args, **kwargs)

        AsyncSession.execute = spy  # type: ignore[method-assign]
        try:
            await itv._collect_metrics(session, scope)
        finally:
            AsyncSession.execute = original  # type: ignore[method-assign]
        bind = session.get_bind()
        checked: list[str] = []
        for stmt in captured:
            sql = str(stmt.compile(dialect=bind.dialect, compile_kwargs={"literal_binds": True}))
            sql = sql.replace("LIMIT ? OFFSET", "LIMIT -1 OFFSET")
            if "metric_breach_count" in sql:
                kind = "capped"
            elif "metric_intervals" in sql:
                kind = "intervals"
            else:
                continue
            conn = await session.connection()
            rows = (await conn.exec_driver_sql("EXPLAIN QUERY PLAN " + sql)).all()
            plan = "\n".join(str(r[-1]) for r in rows)
            assert sql.count(hint) == expected_reads, sql
            assert sql.count("INDEXED BY") == expected_reads, sql
            table_lines = [line for line in plan.splitlines() if " metric_samples " in f"{line} "]
            assert len(table_lines) == expected_reads, plan
            for line in table_lines:
                assert "ix_metric_samples_vcenter_metric_sampled_value (vcenter_id=? AND metric_key=?" in line, plan
                assert "sampled_at>? AND sampled_at<?" in line, plan
            # hits0 は entity_type も読むので被覆にならない。被覆になるのは capped と matching_series
            if kind == "capped" or entity:
                assert covering_range in plan, plan
            assert "ix_metric_samples_vcenter_entity_metric_sampled (vcenter_id=?)" not in plan, plan
            if kind == "intervals":
                assert "SEARCH metric_prev USING" in plan, plan
            checked.append(kind)
        assert checked == ["capped", "intervals"], checked


@pytest.mark.asyncio
async def test_incident_timeline_all_sources_on_each_dialect(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API の経路と同じ入口（build_incident_timeline_view）で、4 種類すべて・vCenter の指定あり・行数の上限での
    省略を両方の方言で通す（API のテストは conftest が SQLite に固定しているので、PostgreSQL はここで確かめる）。"""
    from vcenter_event_assistant.settings_binding import require_settings

    v1, v2 = uuid.uuid4(), uuid.uuid4()
    for vid, name in ((v1, "vc-a"), (v2, "vc-b")):
        session.add(VCenter(id=vid, name=name, host="h", port=443, username="u", password="p"))
    await session.flush()
    offsets = itertools.count(1)

    def at(minute: float) -> datetime:
        return FROM + timedelta(minutes=minute)

    for vid in (v1, v2):
        session.add(
            EventRecord(
                vcenter_id=vid, occurred_at=at(1), event_type="E", message="m", entity_name="esx01",
                vmware_key=next(_keys), notable_score=50,
            )
        )
        for moid, minute in (("host-1", 2), ("host-2", 3)):
            session.add(
                MetricSample(
                    vcenter_id=vid, sampled_at=at(minute), entity_type="HostSystem", entity_moid=moid,
                    entity_name="", metric_key=METRIC_CPU, value=90.0,
                )
            )
        for kind, minute in (("vmkernel", 4), ("hostd", 5)):
            session.add(
                LogRecord(
                    vcenter_id=vid, collector_id="c", source_id="s", host="esx01.example.com", log_kind=kind,
                    file_generation="g", byte_offset=next(offsets), occurred_at=None, collected_at=at(minute),
                    effective_at=at(minute), severity="ERROR", message=f"log {kind}",
                )
            )
    rule = AlertRule(name="r", rule_type="event_score", alert_level="warning", config={})
    session.add(rule)
    await session.flush()
    session.add(
        AlertHistory(
            rule_id=rule.id, alert_level="warning", state="firing", context_key="E",
            notified_at=at(6), channel="none",
        )
    )
    await session.flush()

    out = await build_incident_timeline_view(
        session, IncidentTimelineViewRequest(from_time=FROM, to_time=TO, vcenter_id=v1), owner_key="dialect-test"
    )
    assert [(i.kind, i.vcenter_id) for i in out.items] == [
        ("event", v1), ("metric", v1), ("metric", v1), ("log", v1), ("log", v1), ("alert", None),
    ]
    assert out.omitted_sources == []
    # 名前が空の系列は moid で表示し、その moid で絞れる（vCenter の指定ありの経路）
    by_moid = await build_incident_timeline_view(
        session,
        IncidentTimelineViewRequest(from_time=FROM, to_time=TO, vcenter_id=v1, entity="host-2", sources=["metric"]),
        owner_key="dialect-test",
    )
    assert [(i.entity_name, i.vcenter_id) for i in by_moid.items] == [("host-2", v1)]

    # 上限 1 行: イベント・アラートは 1 行ずつなので返り、メトリクス・ログ（2 行ずつ）は省く
    monkeypatch.setattr(require_settings(), "context_aggregation_max_rows", 1)
    out = await build_incident_timeline_view(
        session, IncidentTimelineViewRequest(from_time=FROM, to_time=TO, vcenter_id=v1), owner_key="dialect-test"
    )
    assert [i.kind for i in out.items] == ["event", "alert"]
    assert [(o.source, o.reason) for o in out.omitted_sources] == [("metric", "too_many_rows"), ("log", "too_many_rows")]
    assert sum(b.log_error for b in out.overview) == 2


@pytest.mark.asyncio
async def test_incident_timeline_breaching_sample_limit_on_each_dialect(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """閾値以上のサンプルの数の上限（数え上げ・対象で絞る系列の IN）を両方の方言で通す。"""
    from vcenter_event_assistant.settings_binding import require_settings

    vid = uuid.uuid4()
    session.add(VCenter(id=vid, name="vc-limit", host="h", port=443, username="u", password="p"))
    await session.flush()

    def at(minute: float) -> datetime:
        return FROM + timedelta(minutes=minute)

    for moid, name, minutes in (("h1", "esx01", (0, 5, 10)), ("h2", "esx02", (0, 5)), ("h3", "  ", (0,))):
        for minute in minutes:
            session.add(
                MetricSample(
                    vcenter_id=vid, sampled_at=at(minute), entity_type="HostSystem", entity_moid=moid,
                    entity_name=name, metric_key=METRIC_CPU, value=90.0,
                )
            )
    # 閾値未満は数えない
    session.add(
        MetricSample(
            vcenter_id=vid, sampled_at=at(20), entity_type="HostSystem", entity_moid="h1",
            entity_name="esx01", metric_key=METRIC_MEM, value=50.0,
        )
    )
    session.add(
        EventRecord(
            vcenter_id=vid, occurred_at=at(1), event_type="E", message="m", entity_name="esx01",
            vmware_key=next(_keys), notable_score=50,
        )
    )
    await session.flush()

    async def view(limit: int, **kw: object) -> tuple[list[str], list[tuple[str, str]]]:
        monkeypatch.setattr(require_settings(), "timeline_metric_breach_sample_limit", limit)
        out = await build_incident_timeline_view(
            session,
            IncidentTimelineViewRequest(from_time=FROM, to_time=TO, sources=["event", "metric"], **kw),
            owner_key="dialect-test",
        )
        return [i.entity_name or "" for i in out.items], [(o.source, o.reason) for o in out.omitted_sources]

    # 合計 6 件: 5 件なら省く（イベントは返す）、6 件なら区間を返す
    assert await view(5) == (["esx01"], [("metric", "too_many_rows")])
    assert await view(6) == (["esx01", "esx02", "h3", "esx01"], [])
    assert await view(5, vcenter_id=vid) == (["esx01"], [("metric", "too_many_rows")])
    # 対象で絞った後の数で判定する（名前が空の系列は moid で当てる）
    assert await view(3, entity="esx01") == (["esx01", "esx01"], [])
    assert await view(2, entity="esx01") == (["esx01"], [("metric", "too_many_rows")])
    assert await view(1, entity="h3", vcenter_id=vid) == (["h3"], [])


@pytest.mark.asyncio
async def test_metrics_list_vcenter_clauses_by_dialect(session: AsyncSession) -> None:
    """メトリクス一覧の vCenter の条件: 未指定で登録済みの vCenter を並べるのは SQLite のときだけ（Issue #324）。

    方言名を引数で渡すので、CI（SQLite だけ）でも PostgreSQL 向けの分岐を確かめられる。
    """
    from sqlalchemy.sql import operators
    from sqlalchemy.sql.elements import BinaryExpression, BindParameter

    from vcenter_event_assistant.api.routes.metrics import _metric_list_vcenter_clauses

    def vcenter_condition(clauses: list | None) -> tuple[object, object]:
        """条件が vcenter_id の列に対する 1 つの比較であることを確かめ、演算子と右辺の値を返す。

        SQLAlchemy の SQL の描き方やバインド名に依らないよう、式の構造を見る。
        """
        assert clauses is not None and len(clauses) == 1, clauses
        clause = clauses[0]
        assert isinstance(clause, BinaryExpression), clause
        # ORM の属性から作った式の左辺は注釈付きの列なので、is ではなく compare で比べる
        assert clause.left.compare(MetricSample.__table__.c.vcenter_id), clause.left
        assert isinstance(clause.right, BindParameter), clause.right
        return clause.operator, clause.right.value

    # vCenter が 1 つも無い: SQLite は問い合わせずに空で返す合図（None）、PostgreSQL は条件を足さない
    assert await _metric_list_vcenter_clauses(session, None, dialect_name="sqlite") is None
    assert await _metric_list_vcenter_clauses(session, None, dialect_name="postgresql") == []

    v1, v2 = uuid.uuid4(), uuid.uuid4()
    for vid in (v1, v2):
        session.add(VCenter(id=vid, name=f"vc-{vid.hex[:6]}", host="h", port=443, username="u", password="p"))
    await session.flush()

    op, value = vcenter_condition(await _metric_list_vcenter_clauses(session, None, dialect_name="sqlite"))
    assert op is operators.in_op
    assert isinstance(value, list) and set(value) == {v1, v2}
    assert await _metric_list_vcenter_clauses(session, None, dialect_name="postgresql") == []
    # 指定したときは方言に関係なく、その vCenter で絞る
    for dialect_name in ("sqlite", "postgresql"):
        op, value = vcenter_condition(await _metric_list_vcenter_clauses(session, v1, dialect_name=dialect_name))
        assert op is operators.eq
        assert value == v1


@pytest.mark.asyncio
async def test_metrics_list_on_each_dialect(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """メトリクス一覧 API（list_metrics）を両方の方言で通す。vCenter 未指定で両方の vCenter のサンプルを返し、
    vCenter の条件は SQLite だけに付く（Issue #324）。API のテストは conftest が SQLite に固定している。"""
    from fastapi import Response

    from vcenter_event_assistant.api.routes.metrics import list_metrics

    await _seed(session)
    dialect_name = session.get_bind().dialect.name
    captured: list[object] = []
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(statement)
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", spy)
    for from_time, to_time, limit in ((FROM, TO, 10000), (None, None, 500)):
        captured.clear()
        response = Response()
        out = await list_metrics(
            response,
            session,
            vcenter_id=None,
            metric_key=METRIC_CPU,
            from_time=from_time,
            to_time=to_time,
            entity_moid=None,
            limit=limit,
        )
        # CPU のサンプルは 6 件（v1 が 5 件、v2 が 1 件。TO ちょうども含む）
        assert out.total == 6
        assert response.headers["X-Total-Count"] == "6"
        assert len(out.points) == 6
        assert len({p.vcenter_id for p in out.points}) == 2
        metric_sql = [
            str(stmt.compile(dialect=session.get_bind().dialect))  # type: ignore[attr-defined]
            for stmt in captured
            if "FROM metric_samples" in str(stmt)
        ]
        assert len(metric_sql) == 2  # 件数と一覧
        # 条件の形は test_metrics_list_vcenter_clauses_by_dialect で見るので、ここは WHERE に列が出るかだけを見る
        for s in metric_sql:
            where = s.split("WHERE", 1)[1]
            assert ("vcenter_id" in where) is (dialect_name == "sqlite"), s
