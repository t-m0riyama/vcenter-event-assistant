"""Track the authorization generation of users and sessions."""

import sqlalchemy as sa
from alembic import op

revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None

_COLUMN = "authorization_generation"


def upgrade() -> None:
    for table in ("users", "auth_sessions"):
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
        if _COLUMN not in columns:
            op.add_column(table, sa.Column(_COLUMN, sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    for table in ("auth_sessions", "users"):
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
        if _COLUMN in columns:
            op.drop_column(table, _COLUMN)
