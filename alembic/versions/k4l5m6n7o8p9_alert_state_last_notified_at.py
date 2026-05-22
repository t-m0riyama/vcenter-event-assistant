"""alert_states: last_notified_at and unique (rule_id, context_key)

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
Create Date: 2026-05-23 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "k4l5m6n7o8p9"
down_revision = "j3k4l5m6n7o8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alert_states",
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE alert_states SET last_notified_at = fired_at "
            "WHERE last_notified_at IS NULL"
        )
    )
    op.create_unique_constraint(
        "uq_alert_states_rule_id_context_key",
        "alert_states",
        ["rule_id", "context_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_alert_states_rule_id_context_key",
        "alert_states",
        type_="unique",
    )
    op.drop_column("alert_states", "last_notified_at")
