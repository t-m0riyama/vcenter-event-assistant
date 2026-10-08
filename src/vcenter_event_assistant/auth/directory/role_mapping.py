"""グループ DN の正規化と、所属グループからのロール決定。"""

from __future__ import annotations

from collections.abc import Iterable

from ldap3.core.exceptions import LDAPInvalidDnError
from ldap3.utils.dn import parse_dn

from vcenter_event_assistant.auth.roles import Role

_ROLE_ORDER = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}


def normalize_dn(dn: str) -> str:
    """照合用の DN。属性名・値の大文字小文字と、区切りの前後の空白の違いをならす。

    AD / LDAP の DN の比較は（ほとんどの属性で）大文字小文字を区別しないため、対応表に登録した
    DN とディレクトリが返す DN の表記ゆれで一致しなくならないようにする。
    """
    value = dn.strip()
    try:
        parts = parse_dn(value, escape=False, strip=True)
    except (LDAPInvalidDnError, IndexError, ValueError):
        return value.casefold()
    # 区切り（RDN の間の ``,`` と、複数値 RDN の中の ``+``）は保つ。``cn=a+uid=b`` と ``cn=a,uid=b`` は別の DN
    return "".join(f"{attr.strip().casefold()}={val.strip().casefold()}{sep}" for attr, val, sep in parts)


def resolve_role(group_dns: Iterable[str], mappings: Iterable[tuple[str, Role]]) -> Role | None:
    """所属グループ（正規化済み DN）と対応表から、最も強いロールを返す。どれにも一致しなければ ``None``。"""
    groups = set(group_dns)
    best: Role | None = None
    for normalized, role in mappings:
        if normalized in groups and (best is None or _ROLE_ORDER[role] > _ROLE_ORDER[best]):
            best = role
    return best
