"""Users and login sessions for built-in authentication.

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
"""

from alembic import op
import sqlalchemy as sa

revision = "z7a8b9c0d1e2"
down_revision = "y6z7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # Legacy fingerprint stamping may replay this migration against a newer schema.
    if not inspector.has_table("users"):
        _create_users()
    if not inspector.has_table("auth_sessions"):
        _create_auth_sessions()


def _create_users() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("realm_key", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("username", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("directory_id", sa.Uuid(), nullable=True),
        sa.Column("password_hash", sa.String(512), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("realm_key", "subject", name="uq_users_realm_subject"),
        sa.CheckConstraint("role IN ('admin', 'operator', 'viewer')", name="ck_users_role"),
    )
    op.create_index("ix_users_directory_id", "users", ["directory_id"])


def _create_auth_sessions() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(256), nullable=True),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("auth_sessions")
    op.drop_table("users")
