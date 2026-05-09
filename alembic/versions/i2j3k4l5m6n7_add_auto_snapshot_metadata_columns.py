"""add auto snapshot metadata columns

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-05-09 03:55:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "i2j3k4l5m6n7"
down_revision = "h1i2j3k4l5m6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incident_timeline_manual_snapshots",
        sa.Column(
            "snapshot_kind",
            sa.String(length=16),
            nullable=False,
            server_default="manual",
        ),
    )
    op.add_column(
        "incident_timeline_manual_snapshots",
        sa.Column("trigger_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "incident_timeline_manual_snapshots",
        sa.Column("trigger_evidence", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_incident_timeline_manual_snapshots_snapshot_kind",
        "incident_timeline_manual_snapshots",
        ["snapshot_kind"],
        unique=False,
    )
    op.create_index(
        "ix_incident_timeline_manual_snapshots_trigger_id",
        "incident_timeline_manual_snapshots",
        ["trigger_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_incident_timeline_manual_snapshots_trigger_id", table_name="incident_timeline_manual_snapshots")
    op.drop_index("ix_incident_timeline_manual_snapshots_snapshot_kind", table_name="incident_timeline_manual_snapshots")
    op.drop_column("incident_timeline_manual_snapshots", "trigger_evidence")
    op.drop_column("incident_timeline_manual_snapshots", "trigger_id")
    op.drop_column("incident_timeline_manual_snapshots", "snapshot_kind")
