"""Add the expression index for error logs by normalized severity and effective_at.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-11-16

タイムライン表示（POST /api/incident-timeline/view）のエラーログの一覧と俯瞰は、
``lower(trim(severity)) IN (...)`` と ``effective_at`` の範囲で絞る。既存の effective_at の索引では
期間内のすべてのログ（大半は info / warning）を読んでから捨てるので、同じ式の索引を足す。
SQLite は式が一致しないと索引を使わないため、式は問い合わせ（SQLAlchemy の出力）と同じにする。
表は作り直さない（CREATE INDEX だけ）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None

_INDEX = "ix_log_records_severity_norm_effective"


# SQLAlchemy の inspect は SQLite の式の索引を返さない（警告を出して飛ばす）ので、既存の
# マイグレーションのように get_indexes で有無を確かめられない。IF NOT EXISTS / IF EXISTS で
# 再実行しても失敗しないようにする（SQLite・PostgreSQL のどちらも対応）。
def upgrade() -> None:
    op.create_index(
        _INDEX,
        "log_records",
        [sa.text("lower(trim(severity))"), "effective_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="log_records", if_exists=True)
