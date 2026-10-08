"""add directory_configs.unique_id_attribute

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns("directory_configs")}
    if "unique_id_attribute" not in cols:
        op.add_column("directory_configs", sa.Column("unique_id_attribute", sa.String(128), nullable=True))


def downgrade() -> None:
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns("directory_configs")}
    if "unique_id_attribute" in cols:
        op.drop_column("directory_configs", "unique_id_attribute")
