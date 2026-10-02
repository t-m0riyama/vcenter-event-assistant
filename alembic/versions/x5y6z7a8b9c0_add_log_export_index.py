"""Add the global log export keyset index.

Revision ID: x5y6z7a8b9c0
Revises: w4x5y6z7a8b9
"""

from alembic import op
import sqlalchemy as sa

revision = "x5y6z7a8b9c0"
down_revision = "w4x5y6z7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes("log_records")
    if not any(index["name"] == "ix_log_effective_time_id" for index in indexes):
        op.create_index(
            "ix_log_effective_time_id", "log_records", ["effective_at", "id"]
        )


def downgrade() -> None:
    op.drop_index("ix_log_effective_time_id", table_name="log_records")
