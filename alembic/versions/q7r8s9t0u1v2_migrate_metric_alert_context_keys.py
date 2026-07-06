"""metric_threshold AlertState の context_key を vCenter スコープ形式へ移行

Revision ID: q7r8s9t0u1v2
Revises: p2q3r4s5t6u7
Create Date: 2026-07-07 08:15:00.000000
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "q7r8s9t0u1v2"
down_revision = "p2q3r4s5t6u7"
branch_labels = None
depends_on = None


def _is_vcenter_scoped_context_key(context_key: str) -> bool:
    if ":" not in context_key:
        return False
    prefix, rest = context_key.split(":", 1)
    if not prefix or not rest:
        return False
    try:
        uuid.UUID(prefix)
    except ValueError:
        return False
    return True


def upgrade() -> None:
    bind = op.get_bind()
    vcenter_rows = bind.execute(sa.text("SELECT id FROM vcenters")).fetchall()
    vcenter_ids = [str(row[0]) for row in vcenter_rows]

    state_rows = bind.execute(
        sa.text(
            """
            SELECT s.id, s.context_key
            FROM alert_states s
            JOIN alert_rules r ON r.id = s.rule_id
            WHERE r.rule_type = 'metric_threshold'
            """
        )
    ).fetchall()

    resolved_ts = (
        "datetime('now')" if bind.dialect.name == "sqlite" else "CURRENT_TIMESTAMP"
    )

    for state_id, context_key in state_rows:
        if _is_vcenter_scoped_context_key(context_key):
            continue

        moid = context_key
        sample_rows = bind.execute(
            sa.text(
                """
                SELECT DISTINCT vcenter_id
                FROM metric_samples
                WHERE entity_moid = :moid
                """
            ),
            {"moid": moid},
        ).fetchall()
        sample_vcenter_ids = [str(row[0]) for row in sample_rows]

        if len(sample_vcenter_ids) == 1:
            new_key = f"{sample_vcenter_ids[0]}:{moid}"
            bind.execute(
                sa.text("UPDATE alert_states SET context_key = :new_key WHERE id = :id"),
                {"new_key": new_key, "id": state_id},
            )
        elif len(vcenter_ids) == 1:
            new_key = f"{vcenter_ids[0]}:{moid}"
            bind.execute(
                sa.text("UPDATE alert_states SET context_key = :new_key WHERE id = :id"),
                {"new_key": new_key, "id": state_id},
            )
        else:
            bind.execute(
                sa.text(
                    f"""
                    UPDATE alert_states
                    SET state = 'resolved', resolved_at = {resolved_ts}
                    WHERE id = :id
                    """
                ),
                {"id": state_id},
            )


def downgrade() -> None:
    """データ移行の逆変換は行わない（旧形式への復帰は非対応）。"""
