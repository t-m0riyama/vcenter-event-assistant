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
    # v2 の h1 にだけ別名のサンプルを足す。vCenter をまたいで取り違えると v1 の名前が変わる
    session.add(
        MetricSample(
            vcenter_id=other,
            sampled_at=FROM + timedelta(minutes=30),
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
    # context_key の vCenter ごとに、期間の終わりまでで最も新しい CPU のサンプルの名前で解決する
    assert [(a.vcenter_id, a.entity_name) for a in alerts] == [(vid, "H1"), (other, "H1-ON-V2")]
    assert alerts[0].ref.metric_key == METRIC_CPU
    # HostConnectionLostEvent は直前の期間にある（スコア 0）ので新しい種別ではない
    assert [n.event_type for n in out.highlights.new_event_types] == ["CustomEvent"]
