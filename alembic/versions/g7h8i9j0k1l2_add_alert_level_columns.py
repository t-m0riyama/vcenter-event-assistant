"""add alert_level to alert_rules and alert_history

Revision ID: g7h8i9j0k1l2
Revises: e1f2a3b4c5d6
Create Date: 2026-05-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "alert_rules",
        sa.Column(
            "alert_level",
            sa.String(length=32),
            nullable=False,
            server_default="warning",
        ),
    )
    op.add_column(
        "alert_history",
        sa.Column(
            "alert_level",
            sa.String(length=32),
            nullable=False,
            server_default="warning",
        ),
    )


def downgrade() -> None:
    op.drop_column("alert_history", "alert_level")
    op.drop_column("alert_rules", "alert_level")
