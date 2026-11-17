"""メトリクスのサンプルを vCenter で絞る条件（Issue #310）。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.db.models import MetricSample, VCenter


async def metric_vcenter_clause(
    session: AsyncSession,
    vcenter_id: uuid.UUID | None,
) -> ColumnElement[bool] | None:
    """``MetricSample`` を vCenter で絞る条件を返す。

    vCenter を指定しないときも、登録済みの vCenter の id を並べて渡す。索引
    ix_metric_samples_vcenter_metric_sampled_value（vcenter_id, metric_key, sampled_at, value, ...）を
    vCenter ごとの範囲走査で使えるようにするため（SQLite は統計が無いと、ほかの索引を選んで期間に
    関係なくその指標の全サンプルを読む）。削除済みの vCenter のサンプルは外部キーの CASCADE で残らない
    （SQLite でも、接続ごとに ``PRAGMA foreign_keys=ON`` を有効にしている。``db/session.py`` を参照）。

    Returns:
        条件。vCenter が 1 つも無いときは ``None``（サンプルも無いので、呼び出し側は問い合わせずに
        空の結果を返す）。
    """
    if vcenter_id is not None:
        return MetricSample.vcenter_id == vcenter_id
    vcenter_ids = (await session.execute(select(VCenter.id))).scalars().all()
    if not vcenter_ids:
        return None
    return MetricSample.vcenter_id.in_(vcenter_ids)
