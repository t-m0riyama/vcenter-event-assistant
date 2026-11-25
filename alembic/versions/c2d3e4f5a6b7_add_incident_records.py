"""インシデントの記録と紐付けを追加する。"""

import sqlalchemy as sa
from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def _incident_id() -> sa.Column:
    return sa.Column("incident_id", sa.Uuid, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)


def _added_by() -> sa.Column:
    return sa.Column("added_by", sa.String(256), nullable=False)


def _added_at() -> sa.Column:
    return sa.Column("added_at", sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    # stamp のやり直しで移行が再実行されても、作成済みの表・索引と記録は残す。
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("level", sa.String(16)),
        sa.Column("assignee", sa.String(256)),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column("updated_by", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Uuid, nullable=False),
        sa.CheckConstraint("status IN ('open', 'monitoring', 'resolved')", name="ck_incidents_status"),
        sa.CheckConstraint("(status = 'resolved') = (resolved_at IS NOT NULL)", name="ck_incidents_resolved_at"),
        if_not_exists=True,
    )
    op.create_index("ix_incidents_status_updated_at", "incidents", ["status", "updated_at"], if_not_exists=True)
    op.create_index("ix_incidents_resolved_at", "incidents", ["resolved_at"], if_not_exists=True)
    op.create_table(
        "incident_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        _incident_id(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("author", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_by", sa.String(256)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sqlite_autoincrement=True,
        if_not_exists=True,
    )
    op.create_table(
        "incident_events",
        sa.Column("id", sa.Integer, primary_key=True),
        _incident_id(),
        sa.Column("event_id", sa.Integer, nullable=False),
        sa.Column("vcenter_id", sa.Uuid, nullable=False),
        sa.Column("collector_id", sa.String(64), nullable=False),
        sa.Column("vmware_key", sa.Integer, nullable=False),
        sa.Column("vcenter_name", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(512), nullable=False),
        sa.Column("severity", sa.String(64)),
        sa.Column("notable_score", sa.Integer, nullable=False),
        sa.Column("entity_type", sa.String(256)),
        sa.Column("entity_name", sa.String(1024)),
        sa.Column("entity_moid", sa.String(256)),
        sa.Column("user_name", sa.String(512)),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("user_comment", sa.Text),
        _added_by(),
        _added_at(),
        sa.UniqueConstraint("incident_id", "vcenter_id", "collector_id", "vmware_key", name="uq_incident_events_source"),
        sqlite_autoincrement=True,
        if_not_exists=True,
    )
    op.create_table(
        "incident_alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        _incident_id(),
        sa.Column("alert_history_id", sa.Integer, nullable=False),
        sa.Column("rule_id", sa.Integer, nullable=False),
        sa.Column("rule_name", sa.String(255)),
        sa.Column("rule_type", sa.String(64), nullable=False),
        sa.Column("alert_level", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("context_key", sa.String(512), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vcenter_id", sa.Uuid),
        sa.Column("vcenter_name", sa.String(255)),
        sa.Column("entity_moid", sa.String(256)),
        sa.Column("entity_name", sa.String(1024)),
        _added_by(),
        _added_at(),
        sa.UniqueConstraint("incident_id", "alert_history_id", "occurred_at", name="uq_incident_alerts_source"),
        sqlite_autoincrement=True,
        if_not_exists=True,
    )
    op.create_table(
        "incident_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        _incident_id(),
        sa.Column("snapshot_id", sa.Uuid, sa.ForeignKey("incident_timeline_manual_snapshots.id", ondelete="CASCADE"),
                  nullable=False),
        _added_by(),
        _added_at(),
        sa.UniqueConstraint("incident_id", "snapshot_id", name="uq_incident_snapshots_source"),
        sqlite_autoincrement=True,
        if_not_exists=True,
    )
    for table in ("incident_entries", "incident_events", "incident_alerts", "incident_snapshots"):
        op.create_index(f"ix_{table}_incident_id", table, ["incident_id"], if_not_exists=True)
    op.create_index("ix_incident_snapshots_snapshot_id", "incident_snapshots", ["snapshot_id"], if_not_exists=True)


def downgrade() -> None:
    for table in ("incident_snapshots", "incident_alerts", "incident_events", "incident_entries", "incidents"):
        op.drop_table(table)
