"""Add remote logs and collector log counts.

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
"""

from alembic import op
import sqlalchemy as sa

revision = "v3w4x5y6z7a8"
down_revision = "u2v3w4x5y6z7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "log_records" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "log_records",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "vcenter_id",
                sa.Uuid(),
                sa.ForeignKey("vcenters.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("collector_id", sa.String(64), nullable=False),
            sa.Column("source_id", sa.String(128), nullable=False),
            sa.Column("host", sa.String(512), nullable=False),
            sa.Column("log_kind", sa.String(64), nullable=False),
            sa.Column("file_generation", sa.String(128), nullable=False),
            sa.Column("byte_offset", sa.BigInteger(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("severity", sa.String(64), nullable=True),
            sa.Column("message", sa.Text(), nullable=False),
            sa.UniqueConstraint(
                "vcenter_id",
                "collector_id",
                "source_id",
                "log_kind",
                "file_generation",
                "byte_offset",
                name="uq_log_source_position",
            ),
        )
        op.create_index(
            "ix_log_vcenter_effective_time",
            "log_records",
            ["vcenter_id", "effective_at", "id"],
        )
        for column in ("source_id", "log_kind", "effective_at"):
            op.create_index(f"ix_log_records_{column}", "log_records", [column])
    if "logs_inserted" not in {
        c["name"] for c in sa.inspect(bind).get_columns("collector_run_states")
    }:
        op.add_column(
            "collector_run_states",
            sa.Column(
                "logs_inserted", sa.Integer(), nullable=False, server_default="0"
            ),
        )


def downgrade() -> None:
    op.drop_column("collector_run_states", "logs_inserted")
    op.drop_table("log_records")
