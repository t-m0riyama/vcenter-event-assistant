"""add_event_type_guides

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f7
Create Date: 2026-03-22

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_type_guides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=512), nullable=False),
        sa.Column("general_meaning", sa.Text(), nullable=True),
        sa.Column("typical_causes", sa.Text(), nullable=True),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_type", name="uq_event_type_guides_event_type"),
    )


def downgrade() -> None:
    op.drop_table("event_type_guides")
