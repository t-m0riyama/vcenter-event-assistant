"""add collector provenance and run states

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
"""

from alembic import op
import sqlalchemy as sa

revision = "t1u2v3w4x5y6"
down_revision = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    event_columns = {column["name"] for column in inspector.get_columns("events")}
    event_constraints = {
        item["name"] for item in inspector.get_unique_constraints("events")
    }
    event_indexes = {item["name"] for item in inspector.get_indexes("events")}
    if "collector_id" not in event_columns:
        with op.batch_alter_table("events") as batch:
            batch.add_column(sa.Column("collector_id", sa.String(64), nullable=True))
    op.execute(
        "UPDATE events SET collector_id = 'builtin.vcenter.events' WHERE collector_id IS NULL"
    )
    with op.batch_alter_table("events") as batch:
        batch.alter_column("collector_id", nullable=False)
        if "uq_event_vcenter_vmware_key" in event_constraints:
            batch.drop_constraint("uq_event_vcenter_vmware_key", type_="unique")
        if "ix_events_collector_id" not in event_indexes:
            batch.create_index("ix_events_collector_id", ["collector_id"])
        if "uq_event_collector_vmware_key" not in event_constraints:
            batch.create_unique_constraint(
                "uq_event_collector_vmware_key",
                ["vcenter_id", "collector_id", "vmware_key"],
            )

    inspector = sa.inspect(bind)
    metric_columns = {
        column["name"] for column in inspector.get_columns("metric_samples")
    }
    metric_indexes = {item["name"] for item in inspector.get_indexes("metric_samples")}
    if "collector_id" not in metric_columns:
        with op.batch_alter_table("metric_samples") as batch:
            batch.add_column(sa.Column("collector_id", sa.String(64), nullable=True))
    op.execute(
        "UPDATE metric_samples SET collector_id = CASE WHEN metric_key LIKE 'datastore.%' THEN 'builtin.vcenter.datastore_capacity' WHEN metric_key LIKE 'host.net.%' OR metric_key LIKE 'host.disk.%' THEN 'builtin.vcenter.host_performance' ELSE 'builtin.vcenter.host_quickstats' END WHERE collector_id IS NULL"
    )
    with op.batch_alter_table("metric_samples") as batch:
        batch.alter_column("collector_id", nullable=False)
        if "ix_metric_samples_collector_id" not in metric_indexes:
            batch.create_index("ix_metric_samples_collector_id", ["collector_id"])

    op.execute(
        "UPDATE ingestion_state SET kind = 'builtin.vcenter.events' WHERE kind = 'events'"
    )
    inspector = sa.inspect(bind)
    if "collector_run_states" in inspector.get_table_names():
        return
    op.create_table(
        "collector_run_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "vcenter_id",
            sa.Uuid(),
            sa.ForeignKey("vcenters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("collector_id", sa.String(64), nullable=False),
        sa.Column(
            "collector_version", sa.String(64), nullable=False, server_default=""
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("events_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.UniqueConstraint(
            "vcenter_id", "collector_id", name="uq_collector_run_vcenter_plugin"
        ),
    )
    op.create_index(
        "ix_collector_run_states_collector_id", "collector_run_states", ["collector_id"]
    )
    op.create_index(
        "ix_collector_run_states_status", "collector_run_states", ["status"]
    )


def downgrade() -> None:
    op.drop_table("collector_run_states")
    op.execute(
        "UPDATE ingestion_state SET kind = 'events' WHERE kind = 'builtin.vcenter.events'"
    )
    with op.batch_alter_table("metric_samples") as batch:
        batch.drop_index("ix_metric_samples_collector_id")
        batch.drop_column("collector_id")
    with op.batch_alter_table("events") as batch:
        batch.drop_constraint("uq_event_collector_vmware_key", type_="unique")
        batch.drop_index("ix_events_collector_id")
        batch.drop_column("collector_id")
        batch.create_unique_constraint(
            "uq_event_vcenter_vmware_key", ["vcenter_id", "vmware_key"]
        )
