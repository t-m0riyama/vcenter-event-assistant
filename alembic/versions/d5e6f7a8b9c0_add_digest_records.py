"""add digest_records

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-03-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "digest_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_digest_records_created_at"), "digest_records", ["created_at"], unique=False)
    op.create_index(op.f("ix_digest_records_kind"), "digest_records", ["kind"], unique=False)
    op.create_index(op.f("ix_digest_records_period_end"), "digest_records", ["period_end"], unique=False)
    op.create_index(op.f("ix_digest_records_period_start"), "digest_records", ["period_start"], unique=False)
    op.create_index(op.f("ix_digest_records_status"), "digest_records", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_digest_records_status"), table_name="digest_records")
    op.drop_index(op.f("ix_digest_records_period_start"), table_name="digest_records")
    op.drop_index(op.f("ix_digest_records_period_end"), table_name="digest_records")
    op.drop_index(op.f("ix_digest_records_kind"), table_name="digest_records")
    op.drop_index(op.f("ix_digest_records_created_at"), table_name="digest_records")
    op.drop_table("digest_records")
