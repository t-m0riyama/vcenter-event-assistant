"""add_events_user_comment

Revision ID: f8e9d0c1b2a3
Revises: c4d27748ae50
Create Date: 2026-03-22

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8e9d0c1b2a3"
down_revision: Union[str, Sequence[str], None] = "c4d27748ae50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("user_comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "user_comment")
