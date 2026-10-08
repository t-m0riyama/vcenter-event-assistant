"""グループ DN の正規化と、所属グループからのロール決定。"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from ldap3.core.exceptions import LDAPInvalidDnError
from ldap3.utils.dn import escape_rdn, parse_dn

from vcenter_event_assistant.auth.roles import Role

_ROLE_ORDER = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}

# 標準スキーマ（RFC 4519 など）の命名属性の OID と名前（照合用に小文字）。DN では属性を OID でも書けるので、名前にそろえる。
# どれも equality が caseIgnoreMatch / caseIgnoreIA5Match の属性
_ATTRIBUTE_NAMES_BY_OID = {
    "2.5.4.3": "cn",
    "2.5.4.11": "ou",
    "2.5.4.10": "o",
    "2.5.4.6": "c",
    "2.5.4.7": "l",
    "2.5.4.8": "st",
    "2.5.4.9": "street",
    "2.5.4.4": "sn",
    "2.5.4.42": "givenname",
    "2.5.4.43": "initials",
    "2.5.4.44": "generationqualifier",
    "2.5.4.12": "title",
    "2.5.4.5": "serialnumber",
    "2.5.4.13": "description",
    "2.5.4.15": "businesscategory",
    "2.5.4.46": "dnqualifier",
    "2.5.4.51": "houseidentifier",
    "0.9.2342.19200300.100.1.25": "dc",
    "0.9.2342.19200300.100.1.1": "uid",
    "0.9.2342.19200300.100.1.3": "mail",
}
# 値の比較が大文字小文字を区別しない（equality が caseIgnoreMatch / caseIgnoreIA5Match）と標準スキーマで
# 決まっている命名属性。これ以外の属性は、スキーマ次第で大文字小文字を区別するため値をならさない。
_CASE_INSENSITIVE_ATTRS = frozenset(_ATTRIBUTE_NAMES_BY_OID.values())


# 属性の位置（DN の先頭か、区切りの ``,`` / ``+`` の直後）から始まる、OID で書いた属性（``OID.`` 接頭辞付きも含む）
_OID_ATTRIBUTE = re.compile(r"(\s*)(?:oid\.)?(\d+(?:\.\d+)+)(\s*=)", re.IGNORECASE)


def _attribute_starts(dn: str) -> list[int]:
    """属性が始まる位置（DN の先頭と、エスケープ・引用符の外にある ``,`` / ``+`` の直後）。"""
    starts = [0]
    escaped = quoted = False
    for i, c in enumerate(dn):
        if escaped:
            escaped = False
        elif c == "\\":
            escaped = True
        elif c == '"':
            quoted = not quoted
        elif c in ",+" and not quoted:
            starts.append(i + 1)
    return starts


def _replace_known_oids(dn: str) -> str:
    """既知の OID で書いた属性を名前に置き換える（ldap3 の DN 解析は OID の属性を受け付けないため）。

    置き換えるのは属性の位置だけ。値の中（``\\,`` のようにエスケープした区切りの後など）は変えない。
    標準スキーマにない OID はそのまま残す（解析できない DN として扱われる）。
    """
    pieces: list[str] = []
    last = 0
    for start in _attribute_starts(dn):
        match = _OID_ATTRIBUTE.match(dn, start)
        name = _ATTRIBUTE_NAMES_BY_OID.get(match.group(2)) if match else None
        if match and name:
            pieces.append(dn[last:start])
            pieces.append(f"{match.group(1)}{name}{match.group(3)}")
            last = match.end()
    pieces.append(dn[last:])
    return "".join(pieces)


_HEX_ESCAPE = re.compile(r"\\([0-9A-Fa-f]{2})")


def _unescape_value(text: str) -> str:
    """属性値のエスケープ（``\\,`` や ``\\2C``、UTF-8 のバイト列の ``\\C3\\A9``）を実際の文字に戻す。

    16 進のエスケープは連続するものをバイト列としてまとめて UTF-8 でデコードする。
    戻せないときは ``ValueError``（解析できない DN として扱う）。
    """
    data = bytearray()
    i = 0
    while i < len(text):
        c = text[i]
        if c != "\\":
            data += c.encode("utf-8")
            i += 1
        elif match := _HEX_ESCAPE.match(text, i):
            data.append(int(match.group(1), 16))
            i = match.end()
        elif i + 1 < len(text):
            data += text[i + 1].encode("utf-8")
            i += 2
        else:
            raise ValueError("dangling escape in DN value")
    return data.decode("utf-8")  # 不正なバイト列は UnicodeDecodeError（ValueError）


def _parse(dn: str) -> list[tuple[str, str, str]]:
    """DN を解析し、各属性値のエスケープを戻した ``(属性, 値, 区切り)`` の並びにする。"""
    return [
        (attr, _unescape_value(val.strip()), sep)
        for attr, val, sep in parse_dn(_replace_known_oids(dn), escape=False, strip=True)
    ]


def is_valid_dn(dn: str) -> bool:
    """DN として解析できるか。対応表には、ディレクトリが返す DN と一致し得る値だけを登録させる。"""
    try:
        return bool(_parse(dn.strip()))
    except (LDAPInvalidDnError, IndexError, ValueError):
        return False


def normalize_dn(dn: str) -> str:
    """照合用の DN。属性名の大文字小文字と、区切りの前後の空白の違いをならす。

    値の大文字小文字と空白の連続は、比較で区別しないと決まっている属性（cn・ou・dc など）だけならす。
    値のエスケープは実際の文字に戻してから決まった形でエスケープし直す（``\\,`` と ``\\2C`` は同じ）。
    対応表に登録した DN とディレクトリが返す DN の表記ゆれで一致しなくならないようにしつつ、
    大文字小文字を区別する属性で別のグループを同じものとみなさないため。
    """
    value = dn.strip()
    try:
        parts = _parse(value)
    except (LDAPInvalidDnError, IndexError, ValueError):
        return value.casefold()
    # 区切り（RDN の間の ``,`` と、複数値 RDN の中の ``+``）は保つ。``cn=a+uid=b`` と ``cn=a,uid=b`` は別の DN
    # 複数値 RDN（``+`` でつないだ AVA）の中の順序は意味を持たないので並べ替える。
    # RDN の間（``,``）の順序と、``+`` と ``,`` の違いは保つ（``cn=a+uid=b`` と ``cn=a,uid=b`` は別の DN）
    rdns: list[str] = []
    avas: list[str] = []
    for attr, val, sep in parts:
        name = attr.strip().casefold()
        # caseIgnoreMatch の属性は、Unicode の正規化（NFKC）・大文字小文字・連続する空白と前後の空白の
        # 違いが比較に影響しない（RFC 4518 の文字列の準備）
        text = _prepare_case_ignore(val) if name in _CASE_INSENSITIVE_ATTRS else val
        # 戻した値に区切りなどが含まれ得るので、決まった形でエスケープし直す（空の値はそのまま）
        avas.append(f"{name}={escape_rdn(text) if text else text}")
        if sep != "+":
            rdns.append("+".join(sorted(avas)))
            avas = []
    if avas:
        rdns.append("+".join(sorted(avas)))
    return ",".join(rdns)


def _prepare_case_ignore(value: str) -> str:
    """caseIgnoreMatch で比べる値の準備。NFKC で正規化し、大文字小文字と空白の違いをならす。"""
    folded = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", value).casefold())
    return " ".join(folded.split())


def resolve_role(group_dns: Iterable[str], mappings: Iterable[tuple[str, Role]]) -> Role | None:
    """所属グループ（正規化済み DN）と対応表から、最も強いロールを返す。どれにも一致しなければ ``None``。"""
    groups = set(group_dns)
    best: Role | None = None
    for normalized, role in mappings:
        if normalized in groups and (best is None or _ROLE_ORDER[role] > _ROLE_ORDER[best]):
            best = role
    return best
