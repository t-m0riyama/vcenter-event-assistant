"""障害パターンの問い合わせに使う種別と時刻の複合索引を足す。

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-11-23
"""

from alembic import op
from sqlalchemy import inspect

revision = "f9a0b1c2d3e4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None

_INDEX = "ix_events_event_type_occurred_at"


def _index_exists() -> bool:
    return any(index["name"] == _INDEX for index in inspect(op.get_bind()).get_indexes("events"))


def upgrade() -> None:
    if not _index_exists():
        op.create_index(_INDEX, "events", ["event_type", "occurred_at"], unique=False)


def downgrade() -> None:
    if _index_exists():
        op.drop_index(_INDEX, table_name="events")
