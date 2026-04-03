"""vCenter ID から表示ラベル（一覧表用）を解決する。"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import VCenter


def label_for_vcenter_row(v: VCenter) -> str:
    """1 行分の表示ラベル。``name`` のみ使用し、空なら UUID 先頭 8 文字＋省略記号。接続先 ``host`` は使わない。"""
    name = (v.name or "").strip()
    if name:
        return name
    return f"{str(v.id)[:8]}…"


def fallback_label_from_id(vcid: uuid.UUID) -> str:
    """``vcenters`` に該当行が無いときのフォールバック（UUID 短縮）。"""
    return f"{str(vcid)[:8]}…"


async def load_vcenter_labels_map(
    session: AsyncSession,
    ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """重複を除いて ``vcenters`` から id → 表示ラベルを読み込む。欠損 id は ``fallback_label_from_id``。"""
    unique = list({uid for uid in ids})
    if not unique:
        return {}
    rows = (await session.execute(select(VCenter).where(VCenter.id.in_(unique)))).scalars().all()
    by_id = {r.id: label_for_vcenter_row(r) for r in rows}
    out: dict[uuid.UUID, str] = {}
    for uid in unique:
        out[uid] = by_id.get(uid) or fallback_label_from_id(uid)
    return out
