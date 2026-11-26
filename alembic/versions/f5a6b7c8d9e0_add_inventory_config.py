"""構成の今の値・差分・収集状態を追加する。"""

import sqlalchemy as sa
from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None

_SYNC_TABLE = "inventory_sync_states"
_STATES = "inventory_config_states"
_DIFFS = "inventory_config_diffs"
_SYNC_COLUMNS = {
    "config_instance_uuid": sa.String(256),
    "config_first_success_at": sa.DateTime(timezone=True),
    "config_last_started_at": sa.DateTime(timezone=True),
    "config_last_success_at": sa.DateTime(timezone=True),
    "config_last_failure_at": sa.DateTime(timezone=True),
    "config_last_error": sa.Text(),
    "config_last_warning": sa.Text(),
    "config_last_warning_at": sa.DateTime(timezone=True),
    "config_object_count": sa.Integer(),
    "config_deferred_count": sa.Integer(),
}


def _entity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "vcenter_id",
            sa.Uuid(),
            sa.ForeignKey("vcenters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("moid", sa.String(256), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("entity_type", sa.String(256), nullable=False),
        sa.Column("entity_name", sa.String(1024), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        _STATES,
        *_entity_columns(),
        sa.Column("format", sa.Integer, nullable=False),
        sa.Column("value", sa.JSON, nullable=False),
        sa.Column("value_hash", sa.String(64), nullable=False),
        sa.Column("change_version", sa.String(256)),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "vcenter_id", "moid", "category", name="uq_inventory_config_states_entity"
        ),
        if_not_exists=True,
    )
    op.create_table(
        _DIFFS,
        *_entity_columns(),
        sa.Column("element", sa.String(1024)),
        sa.Column("element_label", sa.String(1024)),
        sa.Column("attribute", sa.String(64)),
        sa.Column("old_value", sa.Text),
        sa.Column("new_value", sa.Text),
        sa.Column("truncated", sa.Boolean, nullable=False),
        sa.Column("changed_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "changed_after <= observed_at", name="ck_inventory_config_diffs_period"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_inventory_config_diffs_entity",
        _DIFFS,
        ["vcenter_id", "moid", "observed_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_inventory_config_diffs_observed",
        _DIFFS,
        ["observed_at"],
        if_not_exists=True,
    )
    # SQLite で途中から再試行しても、既存の収集状態を保持する。
    existing = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(_SYNC_TABLE)
    }
    for name, type_ in _SYNC_COLUMNS.items():
        if name not in existing:
            op.add_column(_SYNC_TABLE, sa.Column(name, type_))


def downgrade() -> None:
    for name in reversed(_SYNC_COLUMNS):
        op.drop_column(_SYNC_TABLE, name)
    op.drop_table(_DIFFS)
    op.drop_table(_STATES)
