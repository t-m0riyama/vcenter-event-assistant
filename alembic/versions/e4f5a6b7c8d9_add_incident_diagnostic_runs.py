"""インシデントの診断結果を保存する。

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
"""

import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 再 stamp や移行途中の再起動でも、保存済みの結果を保持する。
    op.create_table(
        "incident_diagnostic_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("command_kind", sa.String(16), nullable=False),
        sa.Column("command_ref", sa.String(100), nullable=False),
        sa.Column("command_title", sa.String(100), nullable=False),
        sa.Column("command_line", sa.Text(), nullable=False),
        sa.Column("executed", sa.Boolean(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("product", sa.String(16), nullable=False),
        sa.Column("host_name", sa.String(512), nullable=False),
        sa.Column("ssh_host", sa.String(512), nullable=False),
        sa.Column("ssh_port", sa.Integer(), nullable=False),
        sa.Column("ssh_username", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("exit_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("stdout_truncated", sa.Boolean(), nullable=False),
        sa.Column("stderr_truncated", sa.Boolean(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_by", sa.String(256), nullable=False),
        sqlite_autoincrement=True,
        if_not_exists=True,
    )
    op.create_index(
        "ix_incident_diagnostic_runs_incident_id",
        "incident_diagnostic_runs",
        ["incident_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("incident_diagnostic_runs")
