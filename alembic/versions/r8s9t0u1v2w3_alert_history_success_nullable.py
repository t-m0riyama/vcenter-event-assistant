"""alert_history.success を nullable に（SMTP 未設定スキップ用）

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-07-07 08:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "r8s9t0u1v2w3"
down_revision = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None


def _alert_history_columns(bind) -> set[str]:
    return {c["name"] for c in inspect(bind).get_columns("alert_history")}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _alert_history_columns(bind)
    if "success" not in cols:
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("alert_history") as batch_op:
            batch_op.alter_column("success", existing_type=sa.Boolean(), nullable=True)
    else:
        op.alter_column("alert_history", "success", existing_type=sa.Boolean(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("alert_history") as batch_op:
            batch_op.alter_column("success", existing_type=sa.Boolean(), nullable=False)
    else:
        op.alter_column("alert_history", "success", existing_type=sa.Boolean(), nullable=False)
