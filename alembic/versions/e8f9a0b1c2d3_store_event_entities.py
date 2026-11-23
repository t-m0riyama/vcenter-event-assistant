"""イベントの主な対象の moid と、すべての対象を保存する（Issue #347）。

event_entities は events を参照する最初の外部キーを持つ。SQLite の起動時移行は
PRAGMA foreign_keys=ON の接続で流れるため、batch_alter_table で events を作り直すと、
DROP TABLE に伴う暗黙の DELETE が CASCADE を起こし、event_entities の行が消える。
events を作り直す移行では、トランザクション開始前に外部キーを無効にするか、子の行を退避・復元する。
"""

import sqlalchemy as sa
from alembic import op

revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None

_EVENTS_INDEX = "ix_events_vcenter_id_entity_moid"
_ENTITIES_INDEX = "ix_event_entities_vcenter_id_entity_moid"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "entity_moid" not in {column["name"] for column in inspector.get_columns("events")}:
        op.add_column("events", sa.Column("entity_moid", sa.String(256), nullable=True))
    op.create_index(_EVENTS_INDEX, "events", ["vcenter_id", "entity_moid"], if_not_exists=True)

    if not inspector.has_table("event_entities"):
        op.create_table(
            "event_entities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("vcenter_id", sa.Uuid(), nullable=False),
            sa.Column("role", sa.String(64), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False),
            sa.Column("entity_type", sa.String(256), nullable=True),
            sa.Column("entity_moid", sa.String(256), nullable=True),
            sa.Column("entity_name", sa.String(1024), nullable=True),
            sa.UniqueConstraint("event_id", "role", "position", name="uq_event_entities_event_id_role_position"),
        )
    op.create_index(_ENTITIES_INDEX, "event_entities", ["vcenter_id", "entity_moid"], if_not_exists=True)


def downgrade() -> None:
    op.drop_table("event_entities")
    op.drop_index(_EVENTS_INDEX, table_name="events")
    op.drop_column("events", "entity_moid")
