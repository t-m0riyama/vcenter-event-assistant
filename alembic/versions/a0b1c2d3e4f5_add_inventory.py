"""管理対象・関係の履歴・観測時刻・収集状態を追加する。"""

import sqlalchemy as sa
from alembic import op

revision = "a0b1c2d3e4f5"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def _vcenter_id(*, primary_key: bool = False) -> sa.Column:
    return sa.Column(
        "vcenter_id",
        sa.Uuid(),
        sa.ForeignKey("vcenters.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=primary_key,
    )


def upgrade() -> None:
    # 旧 DB の stamp や SQLite での移行の再試行でも、すでに作られた表と索引を残す。
    op.create_table(
        "inventory_objects",
        sa.Column("id", sa.Integer, primary_key=True),
        _vcenter_id(),
        sa.Column("moid", sa.String(256), nullable=False),
        sa.Column("entity_type", sa.String(256), nullable=False),
        sa.Column("name", sa.String(1024), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "vcenter_id", "moid", name="uq_inventory_objects_vcenter_moid"
        ),
        if_not_exists=True,
    )
    op.create_table(
        "inventory_relations",
        sa.Column("id", sa.Integer, primary_key=True),
        _vcenter_id(),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("child_moid", sa.String(256), nullable=False),
        sa.Column("parent_moid", sa.String(256), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_inventory_relations_valid_period",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_inventory_relations_parent",
        "inventory_relations",
        ["vcenter_id", "parent_moid", "kind", "valid_from"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_inventory_relations_child",
        "inventory_relations",
        ["vcenter_id", "child_moid", "kind", "valid_from"],
        if_not_exists=True,
    )
    op.create_index(
        "uq_inventory_relations_open",
        "inventory_relations",
        ["vcenter_id", "kind", "child_moid", "parent_moid"],
        unique=True,
        sqlite_where=sa.text("valid_to IS NULL"),
        postgresql_where=sa.text("valid_to IS NULL"),
        if_not_exists=True,
    )
    op.create_table(
        "inventory_sync_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        _vcenter_id(),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    op.create_index(
        "ix_inventory_sync_runs_observed",
        "inventory_sync_runs",
        ["vcenter_id", "observed_at"],
        if_not_exists=True,
    )
    op.create_table(
        "inventory_sync_states",
        _vcenter_id(primary_key=True),
        sa.Column("instance_uuid", sa.String(256)),
        sa.Column("first_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("last_warning", sa.Text),
        sa.Column("last_warning_at", sa.DateTime(timezone=True)),
        sa.Column("object_count", sa.Integer),
        sa.Column("relation_count", sa.Integer),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("inventory_sync_states")
    op.drop_table("inventory_sync_runs")
    op.drop_table("inventory_relations")
    op.drop_table("inventory_objects")
