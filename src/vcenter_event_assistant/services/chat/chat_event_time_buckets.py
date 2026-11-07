"""期間チャット用のイベント件数バケット（時間軸は period_metrics と同一 ``bucket_sec`` に揃え可能）。"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import EventRecord
from vcenter_event_assistant.services.chat.aggregation_limiter import AggregationLimitExceeded
from vcenter_event_assistant.services.sql_time import bucket_index_expr, truncate_to_second


class EventTimeBucketRow(BaseModel):
    """1 時間バケット内のイベント件数（種別ごと）。"""

    bucket_start_utc: datetime
    total: int = Field(ge=0)
    by_type: dict[str, int] = Field(default_factory=dict)
    alert_top_types: list["AlertTypeBucketRow"] = Field(default_factory=list)
    alert_other_count: int = Field(default=0, ge=0)


class AlertTypeBucketRow(BaseModel):
    """1 バケット内のアラート集約（event_type 単位）。"""

    event_type: str
    count: int = Field(ge=0)
    max_notable_score: int


class EventTimeBucketsPayload(BaseModel):
    """期間内イベントを ``bucket_sec`` 幅で集計したスパース列。"""

    bucket_minutes: int
    from_utc: datetime
    to_utc: datetime
    buckets: list[EventTimeBucketRow]


async def build_chat_event_time_buckets(
    session: AsyncSession,
    from_utc: datetime,
    to_utc: datetime,
    *,
    vcenter_id: uuid.UUID | None,
    bucket_sec: int,
    max_types_per_bucket: int = 10,
    alert_top_n_per_bucket: int = 3,
    max_rows: int | None = None,
) -> EventTimeBucketsPayload:
    """
    ``occurred_at`` を ``bucket_sec`` 幅のバケットに集計する。

    - 件数 0 のバケットは含めない（スパース）。
    - ``by_type`` は件数降順で上位 ``max_types_per_bucket`` 種別を残し、残りは ``_other`` にまとめる。
    - 集計は DB の GROUP BY（バケット × 種別）で行い、イベントを 1 行ずつ読み込まない（Issue #301）。
    - ``max_rows`` を指定すると、集計後の行数がそれを超えたとき ``AggregationLimitExceeded`` を投げる。
    """
    if bucket_sec < 1:
        raise ValueError("bucket_sec must be >= 1")
    if max_types_per_bucket < 1:
        raise ValueError("max_types_per_bucket must be >= 1")
    if alert_top_n_per_bucket < 1:
        raise ValueError("alert_top_n_per_bucket must be >= 1")

    # DB 側のバケット番号は秒単位なので、起点も秒に揃える（呼び出し元で揃えていれば何もしない）。
    from_utc = truncate_to_second(from_utc)
    to_utc = truncate_to_second(to_utc)
    if from_utc >= to_utc:
        raise ValueError("from_utc must be before to_utc")

    clauses = [
        EventRecord.occurred_at >= from_utc,
        EventRecord.occurred_at < to_utc,
    ]
    if vcenter_id is not None:
        clauses.append(EventRecord.vcenter_id == vcenter_id)

    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else "sqlite"
    # SELECT と GROUP BY で式を一致させるため、バケット番号は副問い合わせの列にしてから集計する。
    base = (
        select(
            bucket_index_expr(
                EventRecord.occurred_at,
                dialect_name,
                from_epoch=int(from_utc.timestamp()),
                bucket_sec=bucket_sec,
            ).label("bidx"),
            EventRecord.event_type.label("event_type"),
            func.coalesce(EventRecord.notable_score, 0).label("score"),
        )
        .where(and_(*clauses))
        .subquery("base")
    )
    stmt = select(
        base.c.bidx,
        base.c.event_type,
        func.count().label("cnt"),
        func.max(base.c.score).label("max_score"),
    ).group_by(base.c.bidx, base.c.event_type)
    if max_rows is not None:
        stmt = stmt.limit(max_rows + 1)
    rows = (await session.execute(stmt)).all()
    if max_rows is not None and len(rows) > max_rows:
        raise AggregationLimitExceeded("event_time_buckets", max_rows)

    counts_by_bidx: dict[int, dict[str, int]] = defaultdict(dict)
    alert_stats_by_bidx: dict[int, dict[str, dict[str, int]]] = defaultdict(dict)
    for bidx, event_type, cnt, max_score in rows:
        b = int(bidx)
        et = str(event_type)
        counts_by_bidx[b][et] = int(cnt)
        alert_stats_by_bidx[b][et] = {"count": int(cnt), "max_notable_score": int(max_score or 0)}

    bucket_minutes = max(1, bucket_sec // 60)
    out_rows: list[EventTimeBucketRow] = []
    for bidx in sorted(counts_by_bidx.keys()):
        raw = dict(counts_by_bidx[bidx])
        total = sum(raw.values())
        items = sorted(raw.items(), key=lambda x: (-x[1], x[0]))
        top = items[:max_types_per_bucket]
        rest = items[max_types_per_bucket:]
        by_type: dict[str, int] = {k: v for k, v in top}
        rest_sum = sum(v for _, v in rest)
        if rest_sum:
            by_type["_other"] = rest_sum

        raw_alerts = alert_stats_by_bidx[bidx]
        ranked_alerts = sorted(
            raw_alerts.items(),
            key=lambda x: (
                -int(x[1]["max_notable_score"]),
                -int(x[1]["count"]),
                x[0],
            ),
        )
        top_alerts = ranked_alerts[:alert_top_n_per_bucket]
        rest_alerts = ranked_alerts[alert_top_n_per_bucket:]
        alert_top_types = [
            AlertTypeBucketRow(
                event_type=event_type,
                count=int(stat["count"]),
                max_notable_score=int(stat["max_notable_score"]),
            )
            for event_type, stat in top_alerts
        ]
        alert_other_count = sum(int(stat["count"]) for _, stat in rest_alerts)
        bucket_start = from_utc + timedelta(seconds=bidx * bucket_sec)
        out_rows.append(
            EventTimeBucketRow(
                bucket_start_utc=bucket_start,
                total=total,
                by_type=by_type,
                alert_top_types=alert_top_types,
                alert_other_count=alert_other_count,
            ),
        )

    return EventTimeBucketsPayload(
        bucket_minutes=bucket_minutes,
        from_utc=from_utc,
        to_utc=to_utc,
        buckets=out_rows,
    )
