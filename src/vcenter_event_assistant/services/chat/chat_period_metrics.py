"""期間チャット用メトリクス（時間バケット平均・カテゴリ別トグル）。"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import MetricSample

METRIC_CPU = "host.cpu.usage_pct"
METRIC_MEM = "host.mem.usage_pct"
DISK_KEYS: tuple[str, ...] = (
    "host.disk.read_kbps",
    "host.disk.write_kbps",
    "host.disk.usage_pct",
)
NET_KEYS: tuple[str, ...] = (
    "host.net.bytes_rx_kbps",
    "host.net.bytes_tx_kbps",
    "host.net.usage_kbps",
)


class PeriodMetricBucketPoint(BaseModel):
    """1 バケットの平均と件数。"""

    bucket_start_utc: datetime
    avg: float = Field(description="バケット内の算術平均")
    n: int = Field(description="バケット内サンプル件数")


class PeriodMetricHostSeries(BaseModel):
    """ホスト（または複合 entity）× メトリクス 1 種の時系列。"""

    entity_name: str
    entity_moid: str
    metric_key: str
    series: list[PeriodMetricBucketPoint]


class PeriodMetricsPayload(BaseModel):
    """LLM に渡す期間メトリクス（間引き後）。"""

    bucket_minutes: int
    from_utc: datetime
    to_utc: datetime
    cpu: list[PeriodMetricHostSeries] | None = None
    memory: list[PeriodMetricHostSeries] | None = None
    disk: list[PeriodMetricHostSeries] | None = None
    network: list[PeriodMetricHostSeries] | None = None


def _as_utc(dt: datetime) -> datetime:
    """DB から naive が返る場合は UTC とみなす。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_chat_bucket_seconds(
    from_utc: datetime,
    to_utc: datetime,
    *,
    max_buckets: int = 48,
) -> int:
    """
    メトリクス・イベント時刻バケットで共有するバケット幅（秒）。

    ``build_chat_period_metrics(..., bucket_sec=compute_chat_bucket_seconds(...))`` のように
    他集計と同じ幅に揃える。
    """
    from_utc = _as_utc(from_utc)
    to_utc = _as_utc(to_utc)
    if from_utc >= to_utc:
        raise ValueError("from_utc must be before to_utc")
    return _bucket_seconds_for_range(from_utc, to_utc, max_buckets=max_buckets)


def _bucket_seconds_for_range(
    from_utc: datetime,
    to_utc: datetime,
    *,
    max_buckets: int,
) -> int:
    """期間長に応じたバケット幅（秒）。バケット数が max_buckets を超えないよう切り上げる。"""
    dur_sec = max(1, int((to_utc - from_utc).total_seconds()))
    if dur_sec <= 6 * 3600:
        width = 15 * 60
    elif dur_sec <= 48 * 3600:
        width = 3600
    else:
        width = 6 * 3600
    while dur_sec / width > max_buckets:
        width *= 2
    return int(width)


def _keys_for_toggles(
    include_cpu: bool,
    include_memory: bool,
    include_disk_io: bool,
    include_network_io: bool,
) -> tuple[str, ...]:
    keys: list[str] = []
    if include_cpu:
        keys.append(METRIC_CPU)
    if include_memory:
        keys.append(METRIC_MEM)
    if include_disk_io:
        keys.extend(DISK_KEYS)
    if include_network_io:
        keys.extend(NET_KEYS)
    return tuple(keys)


def _category_for_key(metric_key: str) -> Literal["cpu", "memory", "disk", "network"] | None:
    if metric_key == METRIC_CPU:
        return "cpu"
    if metric_key == METRIC_MEM:
        return "memory"
    if metric_key in DISK_KEYS:
        return "disk"
    if metric_key in NET_KEYS:
        return "network"
    return None


async def build_chat_period_metrics(
    session: AsyncSession,
    from_utc: datetime,
    to_utc: datetime,
    *,
    vcenter_id: uuid.UUID | None,
    include_cpu: bool,
    include_memory: bool,
    include_disk_io: bool,
    include_network_io: bool,
    max_buckets: int = 48,
    max_hosts_per_category: int = 15,
    bucket_sec: int | None = None,
) -> PeriodMetricsPayload | None:
    """
    指定期間のメトリクスを時間バケット平均で集約する。

    - すべてのトグルがオフなら ``None``。
    - ``from_utc >= to_utc`` は ``ValueError``。
    - ``bucket_sec`` を指定するとその幅でバケット化（イベントバケットと揃える用途）。
    """
    from_utc = _as_utc(from_utc)
    to_utc = _as_utc(to_utc)
    if from_utc >= to_utc:
        raise ValueError("from_utc must be before to_utc")
    if not any(
        [include_cpu, include_memory, include_disk_io, include_network_io],
    ):
        return None

    keys = _keys_for_toggles(
        include_cpu,
        include_memory,
        include_disk_io,
        include_network_io,
    )
    if bucket_sec is not None:
        if bucket_sec < 1:
            raise ValueError("bucket_sec must be >= 1")
        bucket_sec_used = bucket_sec
    else:
        bucket_sec_used = _bucket_seconds_for_range(from_utc, to_utc, max_buckets=max_buckets)
    bucket_minutes = max(1, bucket_sec_used // 60)

    clauses = [
        MetricSample.metric_key.in_(keys),
        MetricSample.sampled_at >= from_utc,
        MetricSample.sampled_at < to_utc,
    ]
    if vcenter_id is not None:
        clauses.append(MetricSample.vcenter_id == vcenter_id)

    stmt: Select[tuple[MetricSample]] = select(MetricSample).where(and_(*clauses))
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    # (category, entity_moid, metric_key, bucket_idx) -> sum, count
    acc: dict[tuple[str, str, str, int], list[float]] = defaultdict(list)
    entity_name_by_moid: dict[tuple[str, str], str] = {}

    for r in rows:
        cat = _category_for_key(r.metric_key)
        if cat is None:
            continue
        sampled = _as_utc(r.sampled_at)
        offset_sec = (sampled - from_utc).total_seconds()
        if offset_sec < 0:
            continue
        bidx = int(offset_sec // bucket_sec_used)
        key = (cat, r.entity_moid, r.metric_key, bidx)
        acc[key].append(float(r.value))
        entity_name_by_moid[(cat, r.entity_moid)] = (r.entity_name or "").strip() or r.entity_moid

    # カテゴリ別に entity の代表スコア（期間内の最大バケット平均）で上位 max_hosts を選ぶ
    peak_by_cat_entity: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (cat, moid, mk, _bidx), vals in acc.items():
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        if avg > peak_by_cat_entity[cat][moid]:
            peak_by_cat_entity[cat][moid] = avg

    allowed_moids: dict[str, set[str]] = {}
    for cat, moids in peak_by_cat_entity.items():
        sorted_moids = sorted(moids.keys(), key=lambda m: moids[m], reverse=True)
        allowed_moids[cat] = set(sorted_moids[:max_hosts_per_category])

    def build_series_for_category(
        category: Literal["cpu", "memory", "disk", "network"],
    ) -> list[PeriodMetricHostSeries]:
        allowed = allowed_moids.get(category, set())
        # (moid, metric_key) -> list of (bidx, avg, n)
        per_series: dict[tuple[str, str], dict[int, tuple[float, int]]] = defaultdict(dict)
        for (cat, moid, mk, bidx), vals in acc.items():
            if cat != category or moid not in allowed:
                continue
            s, c = sum(vals), len(vals)
            per_series[(moid, mk)][bidx] = (s / c, c)

        out: list[PeriodMetricHostSeries] = []
        for (moid, mk) in sorted(per_series.keys(), key=lambda x: (x[0], x[1])):
            name = entity_name_by_moid.get((category, moid), moid)
            buckets_map = per_series[(moid, mk)]
            points: list[PeriodMetricBucketPoint] = []
            for bidx in sorted(buckets_map.keys()):
                avg, n = buckets_map[bidx]
                bucket_start = from_utc + timedelta(seconds=bidx * bucket_sec_used)
                points.append(
                    PeriodMetricBucketPoint(bucket_start_utc=bucket_start, avg=avg, n=n),
                )
            out.append(
                PeriodMetricHostSeries(
                    entity_name=name,
                    entity_moid=moid,
                    metric_key=mk,
                    series=points,
                ),
            )
        return out

    payload_cpu = build_series_for_category("cpu") if include_cpu else None
    payload_mem = build_series_for_category("memory") if include_memory else None
    payload_disk = build_series_for_category("disk") if include_disk_io else None
    payload_net = build_series_for_category("network") if include_network_io else None

    return PeriodMetricsPayload(
        bucket_minutes=bucket_minutes,
        from_utc=from_utc,
        to_utc=to_utc,
        cpu=payload_cpu or None,
        memory=payload_mem or None,
        disk=payload_disk or None,
        network=payload_net or None,
    )