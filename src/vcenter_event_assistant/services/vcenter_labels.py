"""vCenter ID から表示ラベル（一覧表用）を解決する。"""

from __future__ import annotations

import ipaddress
import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import VCenter


def _first_label_if_fqdn(host: str) -> str | None:
    """
    接続先がリテラル IP でなく、かつドットを含むとき、先頭ラベル（短縮名）を返す。

    IPv4/IPv6 リテラルは None（短縮ラベルを付けない）。
    """
    h = host.strip()
    if not h or "." not in h:
        return None
    try:
        ipaddress.ip_address(h)
        return None
    except ValueError:
        pass
    first, _sep, _rest = h.partition(".")
    if not first or first == h:
        return None
    return first


def first_hostname_label_if_fqdn(host: str) -> str | None:
    """
    ``entity_name`` 等のホスト文字列が FQDN 形式のとき、先頭ラベル（短縮名）のみを返す。

    LLM 匿名化で FQDN と短縮名を同一エンティティとして別表記登録するために使う。
    """
    return _first_label_if_fqdn(host)


def vcenter_strings_for_anonymization(name: str, host: str) -> list[str]:
    """
    LLM 匿名化で ``vcenter`` カテゴリに登録する文字列（安定順・重複なし）。

    - 登録表示名（``name`` strip）
    - 接続 ``host`` 全文
    - FQDN 形式の ``host`` に対する第1ラベル（表示名・全文と重複しないときのみ）
    """
    n = (name or "").strip()
    h = (host or "").strip()
    parts: list[str] = []
    if n:
        parts.append(n)
    if h:
        parts.append(h)
        if n != h:
            short = _first_label_if_fqdn(h)
            if short and short not in (n, h):
                parts.append(short)
    return list(dict.fromkeys(parts))


async def load_all_vcenter_anonymization_strings(session: AsyncSession) -> list[str]:
    """``vcenters`` 全行から匿名化用文字列を集約する（登録順・重複なし）。"""
    rows = (await session.execute(select(VCenter))).scalars().all()
    out: list[str] = []
    seen: dict[str, None] = {}
    for r in rows:
        for s in vcenter_strings_for_anonymization(r.name, r.host):
            if s not in seen:
                seen[s] = None
                out.append(s)
    return out


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
