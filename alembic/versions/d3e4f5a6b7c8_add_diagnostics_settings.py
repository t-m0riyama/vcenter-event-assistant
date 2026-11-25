"""SSH の用途と診断設定を追加する。"""

import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def _setting_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column("updated_by", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Uuid, nullable=False),
    )


def upgrade() -> None:
    # 版の再 stamp や SQLite で途中まで適用された移行を再実行できるようにする。
    inspector = sa.inspect(op.get_bind())
    for table in ("ssh_credentials", "ssh_connections"):
        if any(column["name"] == "purpose" for column in inspector.get_columns(table)):
            continue
        op.add_column(
            table,
            sa.Column(
                "purpose",
                sa.String(16),
                sa.CheckConstraint(
                    "purpose IN ('logs', 'diagnostics')", name=f"ck_{table}_purpose"
                ),
                nullable=False,
                server_default="logs",
            ),
        )

    op.create_table(
        "diagnostic_targets",
        *_setting_columns(),
        sa.Column(
            "vcenter_id",
            sa.Uuid,
            sa.ForeignKey("vcenters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product", sa.String(16), nullable=False),
        sa.Column("host_moid", sa.String(256)),
        sa.Column("host_name", sa.String(512), nullable=False),
        sa.Column(
            "ssh_connection_id",
            sa.Uuid,
            sa.ForeignKey("ssh_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "product IN ('esxi', 'vcenter')", name="ck_diagnostic_targets_product"
        ),
        sa.CheckConstraint(
            "(product = 'vcenter') = (host_moid IS NULL)",
            name="ck_diagnostic_targets_host_moid",
        ),
        sa.UniqueConstraint(
            "vcenter_id", "host_moid", name="uq_diagnostic_targets_host"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "uq_diagnostic_targets_vcenter",
        "diagnostic_targets",
        ["vcenter_id"],
        unique=True,
        sqlite_where=sa.text("product = 'vcenter'"),
        postgresql_where=sa.text("product = 'vcenter'"),
        if_not_exists=True,
    )

    op.create_table(
        "diagnostic_commands",
        *_setting_columns(),
        sa.Column("product", sa.String(16), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("template", sa.String(1000), nullable=False),
        sa.Column("param_definitions", sa.JSON, nullable=False),
        sa.CheckConstraint(
            "product IN ('esxi', 'vcenter')", name="ck_diagnostic_commands_product"
        ),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("diagnostic_commands")
    op.drop_table("diagnostic_targets")
    for table in ("ssh_connections", "ssh_credentials"):
        # 用途を識別できない旧版に診断用の接続情報を残さない。
        op.execute(sa.text(f"DELETE FROM {table} WHERE purpose = 'diagnostics'"))
        op.drop_column(table, "purpose")
