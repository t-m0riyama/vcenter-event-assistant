"""add composite indexes for events and metric_samples list queries

Revision ID: n1o2p3q4r5s6
Revises: k4l5m6n7o8p9
Create Date: 2026-07-05

一覧 API（/api/events, /api/metrics）の vcenter + 時刻レンジ絞り込み向け。
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect


revision = "n1o2p3q4r5s6"
down_revision = "k4l5m6n7o8p9"
branch_labels = None
depends_on = None

_EVENTS_INDEX = "ix_events_vcenter_id_occurred_at"
_METRICS_INDEX = "ix_metric_samples_vcenter_entity_metric_sampled"


def _index_names(bind, table: str) -> set[str]:
    return {idx["name"] for idx in inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _EVENTS_INDEX not in _index_names(bind, "events"):
        op.create_index(
            _EVENTS_INDEX,
            "events",
            ["vcenter_id", "occurred_at"],
            unique=False,
        )
    if _METRICS_INDEX not in _index_names(bind, "metric_samples"):
        op.create_index(
            _METRICS_INDEX,
            "metric_samples",
            ["vcenter_id", "entity_moid", "metric_key", "sampled_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _EVENTS_INDEX in _index_names(bind, "events"):
        op.drop_index(_EVENTS_INDEX, table_name="events")
    if _METRICS_INDEX in _index_names(bind, "metric_samples"):
        op.drop_index(_METRICS_INDEX, table_name="metric_samples")
