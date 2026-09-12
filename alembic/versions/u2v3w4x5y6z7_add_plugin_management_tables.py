"""add collector plugin settings and installed plugin tables

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
"""

from alembic import op
import sqlalchemy as sa

revision = "u2v3w4x5y6z7"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "collector_plugin_settings" not in tables:
        op.create_table(
            "collector_plugin_settings",
            sa.Column("plugin_id", sa.String(64), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=True),
            sa.Column("interval_seconds", sa.Integer(), nullable=True),
            sa.Column("timeout_seconds", sa.Float(), nullable=True),
            sa.Column("config_values", sa.JSON(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "installed_plugins" not in tables:
        op.create_table(
            "installed_plugins",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("distribution", sa.String(255), nullable=False),
            sa.Column("version", sa.String(64), nullable=False),
            sa.Column("source", sa.String(16), nullable=False),
            sa.Column("origin", sa.String(1024), nullable=False),
            sa.Column("install_path", sa.String(1024), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "distribution", name="uq_installed_plugin_distribution"
            ),
        )
        op.create_index(
            "ix_installed_plugins_distribution", "installed_plugins", ["distribution"]
        )
        op.create_index("ix_installed_plugins_status", "installed_plugins", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "installed_plugins" in tables:
        op.drop_table("installed_plugins")
    if "collector_plugin_settings" in tables:
        op.drop_table("collector_plugin_settings")
