"""add build_request_payload to manual snapshots

Revision ID: h1i2j3k4l5m6
Revises: g7h8i9j0k1l2
Create Date: 2026-05-09

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, Sequence[str], None] = "m0n1o2p3q4r5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "incident_timeline_manual_snapshots",
        sa.Column(
            "build_request_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("incident_timeline_manual_snapshots", "build_request_payload")
