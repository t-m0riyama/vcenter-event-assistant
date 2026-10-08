"""固定ロール（admin ⊃ operator ⊃ viewer）。"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}


def role_at_least(actual: Role | str, required: Role | str) -> bool:
    """``actual`` が ``required`` 以上の権限を持つか。"""
    return Role(actual).rank >= Role(required).rank


def highest_role(roles: Iterable[Role | str]) -> Role | None:
    """最も強いロールを返す。空なら ``None``。"""
    found = [Role(r) for r in roles]
    if not found:
        return None
    return max(found, key=lambda r: r.rank)
