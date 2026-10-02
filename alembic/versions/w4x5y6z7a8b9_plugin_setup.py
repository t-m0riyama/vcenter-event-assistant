"""Common plugin configuration and SSH management."""

from alembic import op
import sqlalchemy as sa

revision = "w4x5y6z7a8b9"
down_revision = "v3w4x5y6z7a8"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "configuration_managed" not in {
        c["name"] for c in inspector.get_columns("collector_plugin_settings")
    }:
        op.add_column(
            "collector_plugin_settings",
            sa.Column(
                "configuration_managed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    tables = set(inspector.get_table_names())

    def create_if_missing(name, *columns):
        if name not in tables:
            op.create_table(name, *columns)

    create_if_missing(
        "plugin_configuration_drafts",
        sa.Column("plugin_id", sa.String(64), primary_key=True),
        sa.Column("config_values", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("tests", sa.JSON(), nullable=False),
    )
    create_if_missing(
        "ssh_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("private_key", sa.Text(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
    )
    create_if_missing(
        "ssh_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("host", sa.String(512), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(512), nullable=False),
        sa.Column(
            "credential_id",
            sa.Uuid(),
            sa.ForeignKey("ssh_credentials.id"),
            nullable=False,
        ),
        sa.Column("candidate_key", sa.Text()),
        sa.Column("approved_key", sa.Text()),
        sa.Column("revision", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_column("collector_plugin_settings", "configuration_managed")
    for name in ("ssh_connections", "ssh_credentials", "plugin_configuration_drafts"):
        op.drop_table(name)
