"""Add indexes for the timeline metric breach and error log queries.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-11-17

タイムライン表示（POST /api/incident-timeline/view）用の索引を 2 つ足す。表は作り直さない（CREATE INDEX だけ）。

- ``ix_metric_samples_vcenter_metric_sampled_value``（vcenter_id, metric_key, sampled_at, value, entity_moid,
  entity_name）、SQLite だけ: 期間内の閾値以上のサンプルを、vCenter・指標ごとの範囲走査で探す。value まで
  含めて、閾値未満の行では表を引かない。これが無いと SQLite は期間内の全指標のサンプルを読み、7 日・200 ホストで
  10 秒を超える。entity_moid・entity_name は、区間を作る前の閾値以上のサンプルの数え上げと、対象に当たる系列の
  探索を、表を引かずに済ませるため。
  PostgreSQL は計測でこの索引を選ばなかった（sampled_at か metric_key の索引を使う）ので作らない。
- ``ix_log_records_vcenter_severity_norm_effective``（vcenter_id, lower(trim(severity)), effective_at）:
  vCenter を指定したエラーログの一覧と俯瞰。SQLite は指定ありだと (vcenter_id, effective_at) の索引を選び、
  期間内の全ログを読む。

索引の作成中は、その表への書き込みが止まる（起動時のマイグレーションもその間待たされる）。目安は
docs/operations/backend-operations.md に書く。

SQLAlchemy の inspect は SQLite の式の索引を返さないので、e2f3a4b5c6d7 と同じく IF NOT EXISTS / IF EXISTS で
再実行しても失敗しないようにする。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None

_METRIC_INDEX = "ix_metric_samples_vcenter_metric_sampled_value"
_LOG_INDEX = "ix_log_records_vcenter_severity_norm_effective"


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.create_index(
            _METRIC_INDEX,
            "metric_samples",
            ["vcenter_id", "metric_key", "sampled_at", "value", "entity_moid", "entity_name"],
            if_not_exists=True,
        )
    op.create_index(
        _LOG_INDEX,
        "log_records",
        ["vcenter_id", sa.text("lower(trim(severity))"), "effective_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(_LOG_INDEX, table_name="log_records", if_exists=True)
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index(_METRIC_INDEX, table_name="metric_samples", if_exists=True)
