"""Add view_request_payload and result_payload to incident timeline manual snapshots.

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-11-18

タイムラインのスナップショットに、保存した時点の view API のリクエストと結果を持たせる。
どちらも NULL 可の列を足すだけ（ADD COLUMN）で、SQLite でも表は作り直さない。既存の行は NULL のまま
（条件だけのスナップショット）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "a4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None

_TABLE = "incident_timeline_manual_snapshots"


def _columns() -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    # 旧 DB の stamp 先から全マイグレーションを流し直すテストがあるので、列があっても失敗しないようにする。
    existing = _columns()
    if "view_request_payload" not in existing:
        op.add_column(_TABLE, sa.Column("view_request_payload", sa.JSON(), nullable=True))
    if "result_payload" not in existing:
        op.add_column(_TABLE, sa.Column("result_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    # SQLite 3.35 以降は DROP COLUMN が使える（表は作り直さない）。
    existing = _columns()
    if "result_payload" in existing:
        op.drop_column(_TABLE, "result_payload")
    if "view_request_payload" in existing:
        op.drop_column(_TABLE, "view_request_payload")
