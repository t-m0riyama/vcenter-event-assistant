"""リモートログに型のキーを足し、版 1 の台帳を開始する。"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

revision = "b1c2d3e4f5a6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None

_VERSION = 1
_LOG_INDEX = "ix_log_vcenter_pattern_effective"


def upgrade() -> None:
    bind = op.get_bind()
    started_at = datetime.now(timezone.utc)
    columns = {column["name"] for column in sa.inspect(bind).get_columns("log_records")}
    sqlite = bind.dialect.name == "sqlite"
    if "pattern_key" not in columns:
        op.add_column("log_records", sa.Column("pattern_key", sa.String(32)))
    if "pattern_version" not in columns:
        op.add_column("log_records", sa.Column("pattern_version", sa.SmallInteger))
    op.create_index(
        _LOG_INDEX, "log_records", ["vcenter_id", "pattern_key", "effective_at"], if_not_exists=True,
    )

    op.create_table(
        "log_patterns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("vcenter_id", sa.Uuid, sa.ForeignKey("vcenters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("log_kind", sa.String(64), nullable=False),
        sa.Column("pattern_key", sa.String(32), nullable=False),
        sa.Column("pattern_version", sa.SmallInteger, nullable=False),
        sa.Column("template", sa.String(500), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.BigInteger, nullable=False),
        sa.Column("max_severity_rank", sa.Integer, nullable=False),
        sa.Column("warning_first_seen_at", sa.DateTime(timezone=True)),
        sa.Column("warning_first_source_id", sa.String(128)),
        sa.UniqueConstraint("vcenter_id", "pattern_key", name="uq_log_patterns_vcenter_key"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_log_patterns_vcenter_first", "log_patterns", ["vcenter_id", "first_seen_at"], if_not_exists=True,
    )
    op.create_index(
        "ix_log_patterns_vcenter_warning_first", "log_patterns", ["vcenter_id", "warning_first_seen_at"],
        if_not_exists=True,
    )
    baselines = op.create_table(
        "log_pattern_baselines",
        sa.Column("vcenter_id", sa.Uuid, sa.ForeignKey("vcenters.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_id", sa.String(128), primary_key=True),
        sa.Column("log_kind", sa.String(64), primary_key=True),
        sa.Column("pattern_version", sa.SmallInteger, primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )
    state = op.create_table(
        "log_pattern_backfill_state",
        sa.Column("pattern_version", sa.SmallInteger, primary_key=True, autoincrement=False),
        sa.Column("upper_id", sa.BigInteger),
        sa.Column("last_id", sa.BigInteger, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("pending_upper_id", sa.BigInteger),
        sa.Column("pending_recorded_at", sa.DateTime(timezone=True)),
        if_not_exists=True,
    )
    logs = sa.table("log_records", sa.column("vcenter_id"), sa.column("source_id"), sa.column("log_kind"))
    kind = sa.func.trim(logs.c.log_kind)
    if not sqlite:
        kind = kind.collate("C")
    sources = sa.select(logs.c.vcenter_id, logs.c.source_id, sa.func.lower(kind)).distinct().subquery()
    vcenters = sa.table("vcenters", sa.column("id"))
    insert = sqlite_insert if sqlite else pg_insert
    # stamp のやり直しで移行が再実行されても、記録済みの開始時刻と進捗は残す。
    # 外部キーが無効だった頃の孤児ログは残し、開始の行は作らない。
    bind.execute(insert(baselines).from_select(
        ["vcenter_id", "source_id", "log_kind", "pattern_version", "started_at"],
        sa.select(sources, sa.literal(_VERSION), sa.literal(started_at, sa.DateTime(timezone=True)))
        .select_from(sources.join(vcenters, sources.c.vcenter_id == vcenters.c.id))
        .where(sa.true()),
    ).on_conflict_do_nothing())
    bind.execute(insert(state).values(pattern_version=_VERSION, last_id=0).on_conflict_do_nothing())


def downgrade() -> None:
    op.drop_table("log_pattern_backfill_state")
    op.drop_table("log_pattern_baselines")
    op.drop_table("log_patterns")
    op.drop_index(_LOG_INDEX, table_name="log_records")
    op.drop_column("log_records", "pattern_version")
    op.drop_column("log_records", "pattern_key")
