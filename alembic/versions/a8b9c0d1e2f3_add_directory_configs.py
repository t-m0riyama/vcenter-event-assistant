"""AD / LDAP directories and group-to-role mappings.

Revision ID: a8b9c0d1e2f3
Revises: z7a8b9c0d1e2
"""

from alembic import op
import sqlalchemy as sa

revision = "a8b9c0d1e2f3"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # Legacy fingerprint stamping may replay this migration against a newer schema.
    if not inspector.has_table("directory_configs"):
        _create_directory_configs()
    if not inspector.has_table("directory_group_role_mappings"):
        _create_mappings()


def _create_directory_configs() -> None:
    op.create_table(
        "directory_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("server_uris", sa.JSON(), nullable=False),
        sa.Column("transport_security", sa.String(8), nullable=False),
        sa.Column("tls_verify", sa.Boolean(), nullable=False),
        sa.Column("ca_cert_pem", sa.Text(), nullable=True),
        sa.Column("bind_dn", sa.String(1024), nullable=True),
        sa.Column("bind_password", sa.String(2048), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("user_search_base", sa.String(1024), nullable=False),
        sa.Column("user_search_filter", sa.String(1024), nullable=True),
        sa.Column("username_attribute", sa.String(128), nullable=True),
        sa.Column("ad_upn_suffix", sa.String(256), nullable=True),
        sa.Column("display_name_attribute", sa.String(128), nullable=True),
        sa.Column("email_attribute", sa.String(128), nullable=True),
        sa.Column("group_mode", sa.String(16), nullable=False),
        sa.Column("group_search_base", sa.String(1024), nullable=True),
        sa.Column("group_search_filter", sa.String(1024), nullable=True),
        sa.Column("group_member_attribute", sa.String(128), nullable=True),
        sa.Column("group_member_value", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('ad', 'ldap')", name="ck_directory_configs_kind"),
        sa.CheckConstraint(
            "transport_security IN ('ldaps', 'starttls', 'none')",
            name="ck_directory_configs_transport",
        ),
        sa.CheckConstraint(
            "group_mode IN ('ad_nested', 'member_of', 'group_search')",
            name="ck_directory_configs_group_mode",
        ),
    )


def _create_mappings() -> None:
    op.create_table(
        "directory_group_role_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "directory_id",
            sa.Uuid(),
            sa.ForeignKey("directory_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("group_dn", sa.String(1024), nullable=False),
        sa.Column("group_dn_normalized", sa.String(1024), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.UniqueConstraint(
            "directory_id", "group_dn_normalized", name="uq_directory_group_role_mappings_group"
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'operator', 'viewer')", name="ck_directory_group_role_mappings_role"
        ),
    )
    op.create_index(
        "ix_directory_group_role_mappings_directory_id",
        "directory_group_role_mappings",
        ["directory_id"],
    )


def downgrade() -> None:
    op.drop_table("directory_group_role_mappings")
    op.drop_table("directory_configs")
