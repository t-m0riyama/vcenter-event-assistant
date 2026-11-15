"""add alert_history.occurred_at (the time of the state transition)

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-11-15

notified_at は配信を試すたびに上書きされるため、出来事の時刻として使えない。
後から変わらない発生時刻の列を足し、既存の行は notified_at の値で埋める。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None

_COLUMN = "occurred_at"
_INDEX = "ix_alert_history_occurred_at"


def _columns(bind) -> set[str]:
    return {c["name"] for c in inspect(bind).get_columns("alert_history")}


def _index_names(bind) -> set[str]:
    return {idx["name"] for idx in inspect(bind).get_indexes("alert_history")}


def upgrade() -> None:
    bind = op.get_bind()
    if _COLUMN not in _columns(bind):
        op.add_column(
            "alert_history",
            sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True),
        )
    op.execute(
        sa.text("UPDATE alert_history SET occurred_at = notified_at WHERE occurred_at IS NULL")
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("alert_history") as batch_op:
            batch_op.alter_column(
                _COLUMN, existing_type=sa.DateTime(timezone=True), nullable=False
            )
    else:
        op.alter_column(
            "alert_history", _COLUMN, existing_type=sa.DateTime(timezone=True), nullable=False
        )
    if _INDEX not in _index_names(bind):
        op.create_index(_INDEX, "alert_history", [_COLUMN], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _INDEX in _index_names(bind):
        op.drop_index(_INDEX, table_name="alert_history")
    if _COLUMN not in _columns(bind):
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("alert_history") as batch_op:
            batch_op.drop_column(_COLUMN)
    else:
        op.drop_column("alert_history", _COLUMN)
