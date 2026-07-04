"""イベント集計クエリ。

API グラフ向けにイベント発生率の時間バケット系列を DB から取得する。
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func, cast, Integer, literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.db.models import EventRecord

def _epoch_seconds_expr(dialect_name: str):
    """``occurred_at`` から UTC エポック秒（整数）を dialect 非依存に算出する。"""
    if dialect_name == "postgresql":
        return cast(func.floor(func.extract("epoch", EventRecord.occurred_at)), Integer)
    return cast(func.strftime("%s", EventRecord.occurred_at), Integer)

async def get_event_rate_series(
    session: AsyncSession,
    event_type: str,
    from_time: datetime,
    to_time: datetime,
    bucket_seconds: int,
    vcenter_id: uuid.UUID | None = None,
) -> list[dict[str, any]]:
    """指定期間のイベント発生数を固定秒バケットで集計する。

    Args:
        session: 非同期 DB セッション。
        event_type: 集計対象のイベント種別。
        from_time: 期間開始（UTC 想定）。
        to_time: 期間終了（UTC 想定）。
        bucket_seconds: バケット幅（秒）。
        vcenter_id: 指定時は当該 vCenter に限定する。

    Returns:
        ``bucket_start``（UTC datetime）と ``count`` を持つ dict のリスト。
        データが無いバケットも count=0 で返す。
    """
    conditions: list[ColumnElement[bool]] = [
        EventRecord.event_type == event_type.strip(),
        EventRecord.occurred_at >= from_time,
        EventRecord.occurred_at <= to_time,
    ]
    if vcenter_id is not None:
        conditions.append(EventRecord.vcenter_id == vcenter_id)

    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else "sqlite"
    epoch_sec = _epoch_seconds_expr(dialect_name)
    bucket_epoch = epoch_sec - func.mod(epoch_sec, literal(bucket_seconds))

    q = (
        select(bucket_epoch.label("bucket_epoch"), func.count().label("cnt"))
        .where(*conditions)
        .group_by(bucket_epoch)
    )
    res = await session.execute(q)
    count_by_epoch: dict[int, int] = {}
    for row in res.all():
        be = int(row.bucket_epoch)
        count_by_epoch[be] = int(row.cnt)

    from_ts = int(from_time.timestamp())
    to_ts = int(to_time.timestamp())
    first = (from_ts // bucket_seconds) * bucket_seconds
    last = (to_ts // bucket_seconds) * bucket_seconds
    
    buckets = []
    for s in range(first, last + bucket_seconds, bucket_seconds):
        dt = datetime.fromtimestamp(s, tz=timezone.utc)
        buckets.append({"bucket_start": dt, "count": count_by_epoch.get(s, 0)})
        
    return buckets
