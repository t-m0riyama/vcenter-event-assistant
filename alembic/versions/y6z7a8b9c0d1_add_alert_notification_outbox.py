"""Durable alert delivery and retry status.

Revision ID: y6z7a8b9c0d1
Revises: x5y6z7a8b9c0
"""

from alembic import op
import sqlalchemy as sa

revision = "y6z7a8b9c0d1"
down_revision = "x5y6z7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("alert_history")}
    columns = (
        sa.Column(
            "delivery_status", sa.String(16), nullable=False, server_default="failed"
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in columns:
        if column.name not in existing:
            op.add_column("alert_history", column)
    # Legacy fingerprint stamping may replay this migration against a newer schema.
    # Never overwrite pending/retrying statuses or replay existing delivery intents.
    if "delivery_status" not in existing:
        op.execute(
            sa.text("""UPDATE alert_history SET delivery_status = CASE
            WHEN success IS NULL THEN 'skipped' WHEN success THEN 'succeeded' ELSE 'failed' END""")
        )
    if inspector.has_table("alert_notification_outbox"):
        indexes = inspector.get_indexes("alert_notification_outbox")
        if not any(index["name"] == "ix_alert_outbox_due" for index in indexes):
            op.create_index(
                "ix_alert_outbox_due",
                "alert_notification_outbox",
                ["next_attempt_at", "created_at"],
            )
        return
    op.create_table(
        "alert_notification_outbox",
        sa.Column(
            "history_id",
            sa.Integer(),
            sa.ForeignKey("alert_history.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("from_address", sa.Text(), nullable=False),
        sa.Column("to_address", sa.Text(), nullable=False),
        sa.Column("message_id", sa.String(255), nullable=False, unique=True),
        sa.Column("notification", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_alert_outbox_due",
        "alert_notification_outbox",
        ["next_attempt_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("alert_notification_outbox")
    for name in (
        "next_attempt_at",
        "last_attempt_at",
        "attempt_count",
        "delivery_status",
    ):
        op.drop_column("alert_history", name)
