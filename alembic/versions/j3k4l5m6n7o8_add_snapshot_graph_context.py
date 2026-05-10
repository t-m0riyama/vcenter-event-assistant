"""add graph_context to incident timeline manual snapshots

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-05-11 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "j3k4l5m6n7o8"
down_revision = "i2j3k4l5m6n7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incident_timeline_manual_snapshots",
        sa.Column("graph_context", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("incident_timeline_manual_snapshots", "graph_context")
