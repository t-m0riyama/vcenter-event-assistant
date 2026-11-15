"""add alert_history.occurred_at (the time of the state transition)

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-11-15

notified_at は配信を試すたびに上書きされるため、出来事の時刻として使えない。
後から変わらない発生時刻の列を足し、既存の行は notified_at の値で埋める。

SQLite では表を作り直さない（batch_alter_table を使わない）。alert_notification_outbox が
alert_history を ON DELETE CASCADE で参照しており、外部キーの検査が有効な接続で表を作り直すと
DROP TABLE の暗黙の DELETE で配信待ちの通知が消えるため。SQLite は既存の列の NULL 可否を
変えられないので、定数の既定値を付けて NOT NULL の列を足し、すぐに notified_at で埋める。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None

_COLUMN = "occurred_at"
_INDEX = "ix_alert_history_occurred_at"
# SQLite で NOT NULL の列を足すための仮の値。追加直後に全行を notified_at で上書きするので残らない。
_SQLITE_PLACEHOLDER = "1970-01-01 00:00:00.000000"


def _columns(bind) -> set[str]:
    return {c["name"] for c in inspect(bind).get_columns("alert_history")}


def _index_names(bind) -> set[str]:
    return {idx["name"] for idx in inspect(bind).get_indexes("alert_history")}


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if _COLUMN not in _columns(bind):
        if sqlite:
            op.add_column(
                "alert_history",
                sa.Column(
                    _COLUMN,
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text(f"'{_SQLITE_PLACEHOLDER}'"),
                ),
            )
            op.execute(sa.text("UPDATE alert_history SET occurred_at = notified_at"))
        else:
            op.add_column(
                "alert_history",
                sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True),
            )
    if not sqlite:
        op.execute(
            sa.text("UPDATE alert_history SET occurred_at = notified_at WHERE occurred_at IS NULL")
        )
        op.alter_column(
            "alert_history", _COLUMN, existing_type=sa.DateTime(timezone=True), nullable=False
        )
    if _INDEX not in _index_names(bind):
        op.create_index(_INDEX, "alert_history", [_COLUMN], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _INDEX in _index_names(bind):
        op.drop_index(_INDEX, table_name="alert_history")
    if _COLUMN in _columns(bind):
        # SQLite でも ALTER TABLE ... DROP COLUMN（3.35 以降）で、表を作り直さずに消す。
        op.drop_column("alert_history", _COLUMN)
