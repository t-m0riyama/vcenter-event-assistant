"""alert_states: last_notified_at and unique (rule_id, context_key)

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
Create Date: 2026-05-23 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "k4l5m6n7o8p9"
down_revision = "j3k4l5m6n7o8"
branch_labels = None
depends_on = None

_LAST_NOTIFIED_COL = sa.Column(
    "last_notified_at", sa.DateTime(timezone=True), nullable=True
)
_UQ_NAME = "uq_alert_states_rule_id_context_key"


def _alert_states_columns(bind) -> set[str]:
    return {c["name"] for c in inspect(bind).get_columns("alert_states")}


def _alert_states_unique_names(bind) -> set[str]:
    return {
        uc["name"]
        for uc in inspect(bind).get_unique_constraints("alert_states")
        if uc.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    cols = _alert_states_columns(bind)
    uq_names = _alert_states_unique_names(bind)
    need_column = "last_notified_at" not in cols
    need_uq = _UQ_NAME not in uq_names

    if need_column or need_uq:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("alert_states") as batch_op:
                if need_column:
                    batch_op.add_column(_LAST_NOTIFIED_COL)
                if need_uq:
                    batch_op.create_unique_constraint(
                        _UQ_NAME,
                        ["rule_id", "context_key"],
                    )
        else:
            if need_column:
                op.add_column("alert_states", _LAST_NOTIFIED_COL)
            if need_uq:
                op.create_unique_constraint(
                    _UQ_NAME,
                    "alert_states",
                    ["rule_id", "context_key"],
                )

    op.execute(
        sa.text(
            "UPDATE alert_states SET last_notified_at = fired_at "
            "WHERE last_notified_at IS NULL"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    cols = _alert_states_columns(bind)
    uq_names = _alert_states_unique_names(bind)
    has_column = "last_notified_at" in cols
    has_uq = _UQ_NAME in uq_names

    if not has_column and not has_uq:
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("alert_states") as batch_op:
            if has_uq:
                batch_op.drop_constraint(_UQ_NAME, type_="unique")
            if has_column:
                batch_op.drop_column("last_notified_at")
    else:
        if has_uq:
            op.drop_constraint(_UQ_NAME, "alert_states", type_="unique")
        if has_column:
            op.drop_column("alert_states", "last_notified_at")
