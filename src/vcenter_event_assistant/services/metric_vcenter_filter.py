"""メトリクスのサンプルを vCenter で絞る条件（Issue #310）。"""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.db.models import MetricSample, VCenter
from vcenter_event_assistant.db.sqlite_hints import indexed_by

# vCenter・指標・期間の順の被覆索引（SQLite だけに作る。``db/models.py`` の ``MetricSample``）
METRIC_COVERING_INDEX = "ix_metric_samples_vcenter_metric_sampled_value"

_SelectT = TypeVar("_SelectT", bound=Select[Any])


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


def pin_metric_covering_index(stmt: _SelectT) -> _SelectT:
    """SQLite のとき、``stmt`` の FROM の ``metric_samples`` を被覆索引に ``INDEXED BY`` で固定する（Issue #334）。

    新しい SQLite（3.51.0 以降で確認）は統計が無いと、UNIQUE 制約の自動索引 (vcenter_id, sampled_at, ...) を選び、
    期間内の全指標の行を読む。被覆索引は指標と期間で範囲を読むので、どの形の問い合わせでも読む量は自動索引より
    多くならない（ディスク上の DB では、表を引かない分も速い）。``ANALYZE`` で統計を作る方法は、すべての問い合わせの
    計画が変わるので使わない。

    ヒントは ``select`` ごとに付く。副問い合わせにするなら ``.subquery()`` の前に付けること。外側の ``select`` に
    付けても内側には伝わらない。別名（``aliased``）の表と PostgreSQL には付かない。索引の無い DB では
    ``no such index`` のエラーになる（索引はマイグレーションとモデルの両方で作る）。
    """
    return stmt.with_hint(
        MetricSample.__table__, indexed_by(METRIC_COVERING_INDEX), dialect_name="sqlite"
    )
