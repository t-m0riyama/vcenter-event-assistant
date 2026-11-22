"""Add a revision token to every alert rule."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None

_PLACEHOLDER = uuid.UUID(int=0)


def upgrade() -> None:
    bind = op.get_bind()
    columns = sa.inspect(bind).get_columns("alert_rules")
    if not any(column["name"] == "revision" for column in columns):
        # An in-place ADD COLUMN preserves rows in the tables referencing alert_rules.
        op.add_column(
            "alert_rules",
            sa.Column("revision", sa.Uuid(), nullable=False, server_default=_PLACEHOLDER.hex),
        )

    rules = sa.table("alert_rules", sa.column("id", sa.Integer()), sa.column("revision", sa.Uuid()))
    ids = bind.scalars(sa.select(rules.c.id).where(rules.c.revision == _PLACEHOLDER)).all()
    if ids:
        bind.execute(
            rules.update().where(rules.c.id == sa.bindparam("rule_id")),
            [{"rule_id": rule_id, "revision": uuid.uuid4()} for rule_id in ids],
        )

    # SQLite needs the constant default for ADD COLUMN and can't remove it in place.
    # The ORM and the import API assign a fresh UUID whenever they insert a rule.
    if bind.dialect.name == "postgresql":
        op.alter_column("alert_rules", "revision", server_default=None)


def downgrade() -> None:
    op.drop_column("alert_rules", "revision")
