"""期間チャット用メトリクス（時間バケット平均・カテゴリ別トグル）。"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, literal, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import MetricSample
from vcenter_event_assistant.services.sql_time import bucket_index_expr, truncate_to_second

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


async def _aggregate_top_hosts(
    session: AsyncSession,
    clauses: list[ColumnElement[bool]],
    *,
    from_utc: datetime,
    bucket_sec: int,
    max_hosts_per_category: int,
) -> tuple[dict[tuple[str, str, str, int], tuple[float, int]], dict[tuple[str, str], str]]:
    """DB でバケット平均を集計し、カテゴリごとの上位ホストの分だけを返す（Issue #301）。

    サンプルを 1 行ずつ読み込まない。上位の選定（期間内のバケット平均の最大値の降順、同点は moid 順）も
    DB の window 関数で行うので、受け取る行数は「カテゴリ数 × 上位件数 × キー数 × バケット数」以下になる。

    層ごとに副問い合わせにしているのは、PostgreSQL で SELECT と GROUP BY の式を一致させるため
    （``sql_time`` のモジュールの説明を参照）。

    Returns:
        ``(category, moid, metric_key, bucket_idx) -> (avg, n)`` と、``(category, moid) -> 表示名``。
    """
    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else "sqlite"
    category = case(
        (MetricSample.metric_key == METRIC_CPU, literal("cpu")),
        (MetricSample.metric_key == METRIC_MEM, literal("memory")),
        (MetricSample.metric_key.in_(DISK_KEYS), literal("disk")),
        else_=literal("network"),
    )
    base = (
        select(
            category.label("cat"),
            MetricSample.entity_moid.label("moid"),
            MetricSample.metric_key.label("mk"),
            bucket_index_expr(
                MetricSample.sampled_at,
                dialect_name,
                from_epoch=int(from_utc.timestamp()),
                bucket_sec=bucket_sec,
            ).label("bidx"),
            MetricSample.value.label("value"),
            MetricSample.entity_name.label("name"),
        )
        .where(and_(*clauses))
        .subquery("base")
    )
    agg = (
        select(
            base.c.cat,
            base.c.moid,
            base.c.mk,
            base.c.bidx,
            func.avg(base.c.value).label("avg"),
            func.count().label("n"),
            # 空や空白だけの名前は NULL にして、名前のある行を優先する（max は NULL を無視する）。
            func.max(func.nullif(func.trim(base.c.name), "")).label("name"),
        )
        .group_by(base.c.cat, base.c.moid, base.c.mk, base.c.bidx)
        .subquery("agg")
    )
    with_peak = select(
        agg,
        func.max(agg.c.avg).over(partition_by=(agg.c.cat, agg.c.moid)).label("peak"),
    ).subquery("with_peak")
    ranked = select(
        with_peak,
        func.dense_rank()
        .over(
            partition_by=with_peak.c.cat,
            order_by=(with_peak.c.peak.desc(), with_peak.c.moid),
        )
        .label("host_rank"),
    ).subquery("ranked")
    stmt = select(
        ranked.c.cat,
        ranked.c.moid,
        ranked.c.mk,
        ranked.c.bidx,
        ranked.c.avg,
        ranked.c.n,
        ranked.c.name,
    ).where(ranked.c.host_rank <= max_hosts_per_category)
    result = await session.execute(stmt)

    acc: dict[tuple[str, str, str, int], tuple[float, int]] = {}
    named: dict[tuple[str, str], str] = {}
    for cat, moid, mk, bidx, avg, n, name in result.all():
        key = (str(cat), str(moid))
        acc[(key[0], key[1], str(mk), int(bidx))] = (float(avg), int(n))
        # SQL の trim は空白文字しか削らないので、タブなどは Python でも落とす。
        display = (name or "").strip()
        if display and display > named.get(key, ""):
            named[key] = display
    # 名前のある行が 1 つもないホストだけ moid を表示名にする。
    names = {key: named.get(key) or key[1] for key in {(c, m) for c, m, _mk, _b in acc}}
    return acc, names


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
    # DB 側のバケット番号は秒単位なので、起点も秒に揃える（呼び出し元で揃えていれば何もしない）。
    from_utc = truncate_to_second(from_utc)
    to_utc = truncate_to_second(to_utc)
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

    acc, entity_name_by_moid = await _aggregate_top_hosts(
        session,
        clauses,
        from_utc=from_utc,
        bucket_sec=bucket_sec_used,
        max_hosts_per_category=max_hosts_per_category,
    )

    def build_series_for_category(
        category: Literal["cpu", "memory", "disk", "network"],
    ) -> list[PeriodMetricHostSeries]:
        # (moid, metric_key) -> {bidx: (avg, n)}
        per_series: dict[tuple[str, str], dict[int, tuple[float, int]]] = defaultdict(dict)
        for (cat, moid, mk, bidx), (avg, n) in acc.items():
            if cat != category:
                continue
            per_series[(moid, mk)][bidx] = (avg, n)

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