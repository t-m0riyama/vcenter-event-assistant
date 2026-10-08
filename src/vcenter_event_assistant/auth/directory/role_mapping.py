"""グループ DN の正規化と、所属グループからのロール決定。"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ldap3.core.exceptions import LDAPInvalidDnError
from ldap3.utils.dn import parse_dn

from vcenter_event_assistant.auth.roles import Role

_ROLE_ORDER = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}

# 標準スキーマ（RFC 4519 など）の命名属性の OID と名前。DN では属性を OID でも書けるので、名前にそろえる
_ATTRIBUTE_NAMES_BY_OID = {
    "2.5.4.3": "cn",
    "2.5.4.11": "ou",
    "2.5.4.10": "o",
    "2.5.4.6": "c",
    "2.5.4.7": "l",
    "2.5.4.8": "st",
    "2.5.4.9": "street",
    "0.9.2342.19200300.100.1.25": "dc",
    "0.9.2342.19200300.100.1.1": "uid",
}
# 値の比較が大文字小文字を区別しない（equality が caseIgnoreMatch / caseIgnoreIA5Match）と標準スキーマで
# 決まっている命名属性。これ以外の属性は、スキーマ次第で大文字小文字を区別するため値をならさない。
_CASE_INSENSITIVE_ATTRS = frozenset(_ATTRIBUTE_NAMES_BY_OID.values())


# RDN の先頭（DN の先頭か ``,`` / ``+`` の直後）にある、OID で書いた属性（``OID.`` 接頭辞付きも含む）
_OID_ATTRIBUTE = re.compile(r"(^|[,+])(\s*)(?:oid\.)?(\d+(?:\.\d+)+)(\s*=)", re.IGNORECASE)


def _replace_known_oids(dn: str) -> str:
    """既知の OID で書いた属性を名前に置き換える（ldap3 の DN 解析は OID の属性を受け付けないため）。

    標準スキーマにない OID はそのまま残す（解析できない DN として扱われる）。
    """

    def replace(match: re.Match[str]) -> str:
        name = _ATTRIBUTE_NAMES_BY_OID.get(match.group(3))
        return f"{match.group(1)}{match.group(2)}{name}{match.group(4)}" if name else match.group(0)

    return _OID_ATTRIBUTE.sub(replace, dn)


def is_valid_dn(dn: str) -> bool:
    """DN として解析できるか。対応表には、ディレクトリが返す DN と一致し得る値だけを登録させる。"""
    try:
        return bool(parse_dn(_replace_known_oids(dn.strip()), escape=False, strip=True))
    except (LDAPInvalidDnError, IndexError, ValueError):
        return False


def normalize_dn(dn: str) -> str:
    """照合用の DN。属性名の大文字小文字と、区切りの前後の空白の違いをならす。

    値の大文字小文字は、比較で区別しないと決まっている属性（cn・ou・dc など）だけならす。
    対応表に登録した DN とディレクトリが返す DN の表記ゆれで一致しなくならないようにしつつ、
    大文字小文字を区別する属性で別のグループを同じものとみなさないため。
    """
    value = dn.strip()
    try:
        parts = parse_dn(_replace_known_oids(value), escape=False, strip=True)
    except (LDAPInvalidDnError, IndexError, ValueError):
        return value.casefold()
    # 区切り（RDN の間の ``,`` と、複数値 RDN の中の ``+``）は保つ。``cn=a+uid=b`` と ``cn=a,uid=b`` は別の DN
    # 複数値 RDN（``+`` でつないだ AVA）の中の順序は意味を持たないので並べ替える。
    # RDN の間（``,``）の順序と、``+`` と ``,`` の違いは保つ（``cn=a+uid=b`` と ``cn=a,uid=b`` は別の DN）
    rdns: list[str] = []
    avas: list[str] = []
    for attr, val, sep in parts:
        name = attr.strip().casefold()
        text = val.strip()
        avas.append(f"{name}={text.casefold() if name in _CASE_INSENSITIVE_ATTRS else text}")
        if sep != "+":
            rdns.append("+".join(sorted(avas)))
            avas = []
    if avas:
        rdns.append("+".join(sorted(avas)))
    return ",".join(rdns)


def resolve_role(group_dns: Iterable[str], mappings: Iterable[tuple[str, Role]]) -> Role | None:
    """所属グループ（正規化済み DN）と対応表から、最も強いロールを返す。どれにも一致しなければ ``None``。"""
    groups = set(group_dns)
    best: Role | None = None
    for normalized, role in mappings:
        if normalized in groups and (best is None or _ROLE_ORDER[role] > _ROLE_ORDER[best]):
            best = role
    return best
