"""Rename the metric key host.disk.usage_pct to host.disk.usage_kbps.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-11-17

``host.disk.usage_pct`` の中身は vSphere のカウンタ ``disk.usage``（average、単位 KBps）で、% ではない
（Issue #316）。名前を単位に合わせ、保存済みの参照を付け替える:

- ``metric_samples.metric_key``
- ``alert_rules.config`` の ``metric_key``（メトリクス閾値のルール）
- ``incident_timeline_manual_snapshots.graph_context`` の ``metric_key``

``alert_history`` の本文に残る古い名前は、履歴なので触らない。

``metric_samples`` は行数が多いと UPDATE に時間がかかる（対象はこの指標の行だけ）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None

_OLD_KEY = "host.disk.usage_pct"
_NEW_KEY = "host.disk.usage_kbps"

# JSON の列は SQLAlchemy の型を通して読み書きする（SQLite と PostgreSQL で同じコードにするため、DB の JSON 関数は使わない）。
_ALERT_RULES = sa.table(
    "alert_rules",
    sa.column("id", sa.Integer),
    sa.column("rule_type", sa.String),
    sa.column("config", sa.JSON),
)
_SNAPSHOTS = sa.table(
    "incident_timeline_manual_snapshots",
    sa.column("id", sa.Uuid(as_uuid=True)),
    sa.column("graph_context", sa.JSON),
)


def _rename_samples(bind: sa.Connection, *, src: str, dst: str) -> None:
    # 付け替え先の名前の行がすでにある点（一意制約 uq_metric_sample_point）は、付け替え元の行を捨てる。
    # 新しいコードが先に書いた行があり得るのは、マイグレーションの前に収集が動いた場合だけ。
    bind.execute(
        sa.text(
            """
            DELETE FROM metric_samples
            WHERE metric_key = :src
              AND EXISTS (
                SELECT 1 FROM metric_samples AS kept
                WHERE kept.metric_key = :dst
                  AND kept.vcenter_id = metric_samples.vcenter_id
                  AND kept.sampled_at = metric_samples.sampled_at
                  AND kept.entity_moid = metric_samples.entity_moid
              )
            """
        ),
        {"src": src, "dst": dst},
    )
    bind.execute(
        sa.text("UPDATE metric_samples SET metric_key = :dst WHERE metric_key = :src"),
        {"src": src, "dst": dst},
    )


def _rename_json_metric_key(
    bind: sa.Connection,
    table: sa.TableClause,
    json_column: sa.ColumnClause,
    *,
    where: sa.ColumnElement[bool] | None,
    src: str,
    dst: str,
) -> None:
    stmt = sa.select(table.c.id, json_column)
    if where is not None:
        stmt = stmt.where(where)
    for row_id, value in bind.execute(stmt).fetchall():
        if not isinstance(value, dict) or value.get("metric_key") != src:
            continue
        bind.execute(
            sa.update(table).where(table.c.id == row_id).values({json_column.name: {**value, "metric_key": dst}})
        )


def _rename(*, src: str, dst: str) -> None:
    bind = op.get_bind()
    _rename_samples(bind, src=src, dst=dst)
    _rename_json_metric_key(
        bind,
        _ALERT_RULES,
        _ALERT_RULES.c.config,
        where=_ALERT_RULES.c.rule_type == "metric_threshold",
        src=src,
        dst=dst,
    )
    _rename_json_metric_key(bind, _SNAPSHOTS, _SNAPSHOTS.c.graph_context, where=None, src=src, dst=dst)


def upgrade() -> None:
    _rename(src=_OLD_KEY, dst=_NEW_KEY)


def downgrade() -> None:
    _rename(src=_NEW_KEY, dst=_OLD_KEY)
