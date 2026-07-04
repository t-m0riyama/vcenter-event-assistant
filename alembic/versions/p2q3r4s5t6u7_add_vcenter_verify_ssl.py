"""add vcenters.verify_ssl

Revision ID: p2q3r4s5t6u7
Revises: n1o2p3q4r5s6
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "p2q3r4s5t6u7"
down_revision = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("vcenters")}
    if "verify_ssl" not in cols:
        op.add_column(
            "vcenters",
            sa.Column("verify_ssl", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if bind.dialect.name != "sqlite":
        op.alter_column("vcenters", "verify_ssl", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("vcenters")}
    if "verify_ssl" in cols:
        op.drop_column("vcenters", "verify_ssl")
