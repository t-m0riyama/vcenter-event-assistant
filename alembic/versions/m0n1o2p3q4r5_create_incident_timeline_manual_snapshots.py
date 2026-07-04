"""create incident_timeline_manual_snapshots base table

Revision ID: m0n1o2p3q4r5
Revises: g7h8i9j0k1l2
Create Date: 2026-07-05

h1 以降の列追加マイグレーションの前提となるベーステーブルを作成する。
従来は init_db の create_all のみで存在していた。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "m0n1o2p3q4r5"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("incident_timeline_manual_snapshots"):
        return

    op.create_table(
        "incident_timeline_manual_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("from_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("operator_note", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_incident_timeline_manual_snapshots_from_time"),
        "incident_timeline_manual_snapshots",
        ["from_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_incident_timeline_manual_snapshots_to_time"),
        "incident_timeline_manual_snapshots",
        ["to_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_incident_timeline_manual_snapshots_timestamp_utc"),
        "incident_timeline_manual_snapshots",
        ["timestamp_utc"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("incident_timeline_manual_snapshots"):
        return
    op.drop_index(
        op.f("ix_incident_timeline_manual_snapshots_timestamp_utc"),
        table_name="incident_timeline_manual_snapshots",
    )
    op.drop_index(
        op.f("ix_incident_timeline_manual_snapshots_to_time"),
        table_name="incident_timeline_manual_snapshots",
    )
    op.drop_index(
        op.f("ix_incident_timeline_manual_snapshots_from_time"),
        table_name="incident_timeline_manual_snapshots",
    )
    op.drop_table("incident_timeline_manual_snapshots")
