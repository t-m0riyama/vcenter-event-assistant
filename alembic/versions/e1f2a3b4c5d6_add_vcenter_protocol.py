"""add vcenter protocol

Revision ID: e1f2a3b4c5d6
Revises: afce65cc22fd
Create Date: 2026-04-24

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "afce65cc22fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("vcenters")}
    if "protocol" not in cols:
        op.add_column(
            "vcenters",
            sa.Column("protocol", sa.String(length=16), nullable=False, server_default="https"),
        )
    op.execute("UPDATE vcenters SET protocol = 'https' WHERE protocol IS NULL")
    # SQLite does not support `ALTER COLUMN ... DROP DEFAULT`.
    if bind.dialect.name != "sqlite":
        op.alter_column("vcenters", "protocol", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("vcenters")}
    if "protocol" in cols:
        op.drop_column("vcenters", "protocol")
