"""vCenter ホスト値の SSRF 対策バリデーション。"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

# クラウドメタデータ等の既知危険アドレス
_BLOCKED_IP_LITERALS = frozenset(
    {
        "169.254.169.254",  # AWS / Azure / GCP metadata
        "fd00:ec2::254",
    }
)

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,512}$)"  # max length aligned with schema
    r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def _normalize_host(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("host must not be empty")
    if "://" in value:
        parsed = urlparse(value)
        if parsed.hostname:
            return parsed.hostname
        raise ValueError("host URL must include a hostname")
    if "/" in value or "?" in value or "#" in value:
        raise ValueError("host must not contain path or query components")
    return value


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if str(ip) in _BLOCKED_IP_LITERALS:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _hostname_allowed_by_suffix(host: str, allowed_suffixes: list[str]) -> bool:
    if not allowed_suffixes:
        return True
    lowered = host.lower()
    for suffix in allowed_suffixes:
        s = suffix.lower().lstrip(".")
        if lowered == s or lowered.endswith(f".{s}"):
            return True
    return False


def validate_vcenter_host(host: str, *, allowed_suffixes: list[str] | None = None) -> str:
    """vCenter 接続先ホストを検証する。SSRF 向けの危険宛先を拒否する。

    Args:
        host: API 入力の host 文字列。
        allowed_suffixes: 本番で許可する FQDN サフィックス（``VCENTER_ALLOWED_HOST_SUFFIXES``）。

    Returns:
        正規化済みホスト名。

    Raises:
        ValueError: 危険または不正な host。
    """
    normalized = _normalize_host(host)
    suffixes = allowed_suffixes or []

    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        if _is_blocked_ip(ip):
            raise ValueError(
                "host resolves to a blocked IP range (private, loopback, link-local, or metadata)"
            )
        return normalized

    if not _HOSTNAME_RE.match(normalized):
        raise ValueError("host must be a valid hostname or public IP address")

    if not _hostname_allowed_by_suffix(normalized, suffixes):
        raise ValueError(
            "host is not allowed; configure VCENTER_ALLOWED_HOST_SUFFIXES for permitted domains"
        )

    return normalized
