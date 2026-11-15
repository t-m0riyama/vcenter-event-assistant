"""add an index on alert_history.notified_at

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-11-15

タイムライン表示（期間での絞り込み）、通知履歴の一覧（降順）、保持期間の削除が
notified_at の範囲・順序で引くのに、インデックスが無く全件を走査していた。
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect


revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None

_INDEX = "ix_alert_history_notified_at"


def _index_names(bind, table: str) -> set[str]:
    return {idx["name"] for idx in inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _INDEX not in _index_names(bind, "alert_history"):
        op.create_index(_INDEX, "alert_history", ["notified_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _INDEX in _index_names(bind, "alert_history"):
        op.drop_index(_INDEX, table_name="alert_history")
