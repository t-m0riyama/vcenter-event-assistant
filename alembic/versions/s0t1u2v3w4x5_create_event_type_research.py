"""event_type 単位の WEB 調査結果キャッシュテーブルを作成

Revision ID: s0t1u2v3w4x5
Revises: r8s9t0u1v2w3
Create Date: 2026-07-08 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "s0t1u2v3w4x5"
down_revision = "r8s9t0u1v2w3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "event_type_research" in inspect(bind).get_table_names():
        return

    op.create_table(
        "event_type_research",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("llm_model", sa.String(length=256), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_type", name="uq_event_type_research_event_type"),
    )
    op.create_index(
        "ix_event_type_research_event_type",
        "event_type_research",
        ["event_type"],
    )
    op.create_index("ix_event_type_research_status", "event_type_research", ["status"])
    op.create_index(
        "ix_event_type_research_searched_at",
        "event_type_research",
        ["searched_at"],
    )


def downgrade() -> None:
    op.drop_table("event_type_research")
