"""build_chat_period_metrics を DB 側で集計したときの動作（Issue #301）。

全件を読み込まずに、上位ホストの選定まで DB で行う。結果は Python で集計していたときと同じにする。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    METRIC_CPU,
    METRIC_MEM,
    build_chat_period_metrics,
)

FROM = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
TO = FROM + timedelta(hours=2)  # 15 分バケット


async def _add_vcenter(session: AsyncSession) -> uuid.UUID:
    vid = uuid.uuid4()
    session.add(VCenter(id=vid, name=f"vc-{vid.hex[:6]}", host="h", port=443, username="u", password="p"))
    await session.flush()
    return vid


def _sample(vid: uuid.UUID, moid: str, key: str, at: datetime, value: float, name: str | None = None) -> MetricSample:
    return MetricSample(
        vcenter_id=vid,
        sampled_at=at,
        entity_type="HostSystem",
        entity_moid=moid,
        entity_name=name if name is not None else moid,
        metric_key=key,
        value=value,
    )


async def _build(session: AsyncSession, **kwargs):
    params = dict(
        vcenter_id=None,
        include_cpu=True,
        include_memory=False,
        include_disk_io=False,
        include_network_io=False,
    )
    params.update(kwargs)
    return await build_chat_period_metrics(session, FROM, TO, **params)


@pytest.mark.asyncio
async def test_bucket_boundary_and_to_exclusion() -> None:
    """境界ちょうどは次のバケット、秒未満は切り捨て、to ちょうどは除外。"""
    async with session_scope() as session:
        vid = await _add_vcenter(session)
        session.add_all(
            [
                _sample(vid, "h1", METRIC_CPU, FROM, 10.0),
                _sample(vid, "h1", METRIC_CPU, FROM + timedelta(minutes=14, seconds=59, microseconds=999_600), 30.0),
                _sample(vid, "h1", METRIC_CPU, FROM + timedelta(minutes=15), 70.0),
                _sample(vid, "h1", METRIC_CPU, TO, 99.0),
            ]
        )
        await session.flush()
        out = await _build(session)
    assert out is not None and out.cpu is not None
    series = out.cpu[0].series
    assert [p.bucket_start_utc for p in series] == [FROM, FROM + timedelta(minutes=15)]
    assert series[0].avg == pytest.approx(20.0)
    assert series[0].n == 2
    assert series[1].avg == pytest.approx(70.0)
    assert series[1].n == 1


@pytest.mark.asyncio
async def test_same_moid_on_two_vcenters_is_merged() -> None:
    """vCenter をまたいで同じ moid は合算する（従来どおり）。"""
    async with session_scope() as session:
        v1 = await _add_vcenter(session)
        v2 = await _add_vcenter(session)
        session.add_all(
            [
                _sample(v1, "host-1", METRIC_CPU, FROM + timedelta(minutes=1), 20.0),
                _sample(v2, "host-1", METRIC_CPU, FROM + timedelta(minutes=2), 40.0),
            ]
        )
        await session.flush()
        out = await _build(session)
    assert out is not None and out.cpu is not None
    assert len(out.cpu) == 1
    assert out.cpu[0].series[0].avg == pytest.approx(30.0)
    assert out.cpu[0].series[0].n == 2


@pytest.mark.asyncio
async def test_top_hosts_are_selected_by_peak_bucket_average_per_category() -> None:
    """カテゴリごとに、バケット平均の最大値が高い順に上位 N 台を残す。"""
    async with session_scope() as session:
        vid = await _add_vcenter(session)
        for i in range(1, 21):
            moid = f"host-{i:02d}"
            # CPU は番号が大きいほど高い。メモリは逆順にして、カテゴリが独立であることを確かめる。
            session.add(_sample(vid, moid, METRIC_CPU, FROM + timedelta(minutes=1), float(i)))
            session.add(_sample(vid, moid, METRIC_CPU, FROM + timedelta(minutes=20), 0.5))
            session.add(_sample(vid, moid, METRIC_MEM, FROM + timedelta(minutes=1), float(100 - i)))
        await session.flush()
        out = await _build(session, include_memory=True, max_hosts_per_category=5)
    assert out is not None and out.cpu is not None and out.memory is not None
    assert sorted(s.entity_moid for s in out.cpu) == [f"host-{i:02d}" for i in range(16, 21)]
    assert sorted(s.entity_moid for s in out.memory) == [f"host-{i:02d}" for i in range(1, 6)]
    # 選ばれたホストは、ピーク以外のバケットも含めて系列が全部返る。
    assert all(len(s.series) == 2 for s in out.cpu)


@pytest.mark.asyncio
async def test_hosts_whose_peak_is_not_positive_are_still_listed() -> None:
    """最大のバケット平均が 0 以下のホストも、上限に収まるなら出力する（従来どおり）。

    従来の Python 版は ``defaultdict(float)`` を比較で参照した時点で登録していたため、
    値が 0 以下のホストも候補に入っていた。
    """
    async with session_scope() as session:
        vid = await _add_vcenter(session)
        session.add_all(
            [
                _sample(vid, "busy", METRIC_CPU, FROM + timedelta(minutes=1), 5.0),
                _sample(vid, "idle", METRIC_CPU, FROM + timedelta(minutes=1), 0.0),
                _sample(vid, "negative", METRIC_CPU, FROM + timedelta(minutes=1), -1.0),
            ]
        )
        await session.flush()
        out = await _build(session)
        limited = await _build(session, max_hosts_per_category=1)
    assert out is not None and out.cpu is not None
    assert sorted(s.entity_moid for s in out.cpu) == ["busy", "idle", "negative"]
    assert limited is not None and limited.cpu is not None
    assert [s.entity_moid for s in limited.cpu] == ["busy"]


@pytest.mark.asyncio
async def test_entity_name_falls_back_to_moid_when_blank() -> None:
    async with session_scope() as session:
        vid = await _add_vcenter(session)
        session.add(_sample(vid, "host-9", METRIC_CPU, FROM + timedelta(minutes=1), 5.0, name="  "))
        await session.flush()
        out = await _build(session)
    assert out is not None and out.cpu is not None
    assert out.cpu[0].entity_name == "host-9"


@pytest.mark.asyncio
async def test_entity_name_prefers_non_blank_name_over_moid() -> None:
    """一部の行の名前が空でも、名前のある行があればその名前を使う（moid に化けない）。"""
    async with session_scope() as session:
        vid = await _add_vcenter(session)
        session.add_all(
            [
                _sample(vid, "host-10", METRIC_CPU, FROM + timedelta(minutes=1), 5.0, name=""),
                _sample(vid, "host-10", METRIC_CPU, FROM + timedelta(minutes=20), 6.0, name=" esx-a.example "),
            ]
        )
        await session.flush()
        out = await _build(session)
    assert out is not None and out.cpu is not None
    assert out.cpu[0].entity_name == "esx-a.example"


@pytest.mark.asyncio
async def test_vcenter_filter_is_applied() -> None:
    async with session_scope() as session:
        v1 = await _add_vcenter(session)
        v2 = await _add_vcenter(session)
        session.add_all(
            [
                _sample(v1, "a", METRIC_CPU, FROM + timedelta(minutes=1), 5.0),
                _sample(v2, "b", METRIC_CPU, FROM + timedelta(minutes=1), 6.0),
            ]
        )
        await session.flush()
        out = await _build(session, vcenter_id=v1)
    assert out is not None and out.cpu is not None
    assert [s.entity_moid for s in out.cpu] == ["a"]


@pytest.mark.asyncio
async def test_query_returns_aggregated_rows_not_orm_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    """メトリクスのサンプルを 1 行ずつ読まず、集計済みの列だけを受け取る。"""
    statements: list[object] = []
    original = AsyncSession.execute

    async def spy(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        statements.append(statement)
        return await original(self, statement, *args, **kwargs)

    async with session_scope() as session:
        vid = await _add_vcenter(session)
        for m in range(0, 120, 5):
            session.add(_sample(vid, "h1", METRIC_CPU, FROM + timedelta(minutes=m), 10.0))
        await session.flush()
        monkeypatch.setattr(AsyncSession, "execute", spy)
        out = await _build(session)
    assert out is not None and out.cpu is not None
    assert sum(p.n for p in out.cpu[0].series) == 24
    assert len(statements) == 1
    columns = {c.key for c in statements[0].selected_columns}  # type: ignore[attr-defined]
    assert columns == {"cat", "moid", "mk", "bidx", "avg", "n", "name"}
