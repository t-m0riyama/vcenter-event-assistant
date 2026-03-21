"""add_event_score_rules

Revision ID: a1b2c3d4e5f7
Revises: f8e9d0c1b2a3
Create Date: 2026-03-22

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "f8e9d0c1b2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_score_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=512), nullable=False),
        sa.Column("score_delta", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_type", name="uq_event_score_rules_event_type"),
    )
    op.create_index(
        op.f("ix_event_score_rules_event_type"),
        "event_score_rules",
        ["event_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_event_score_rules_event_type"), table_name="event_score_rules")
    op.drop_table("event_score_rules")
