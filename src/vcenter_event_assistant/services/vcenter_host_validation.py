"""vCenter ホスト値の SSRF 対策バリデーション。"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

# クラウドメタデータ等の既知危険アドレス
_BLOCKED_IP_LITERALS = frozenset(
    {
        "169.254.169.254",  # AWS / Azure / GCP metadata
        "fd00:ec2::254",
    }
)

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.goog",
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


def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"host could not be resolved: {host}") from exc
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip = ipaddress.ip_address(sockaddr[0])
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise ValueError(f"host could not be resolved: {host}")
    return ips


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
    lowered = normalized.lower()

    if lowered in _BLOCKED_HOSTNAMES or lowered.endswith(".localhost"):
        raise ValueError("host is blocked (localhost or cloud metadata hostname)")

    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        if suffixes:
            raise ValueError(
                "IP literals are not allowed when VCENTER_ALLOWED_HOST_SUFFIXES is configured; use an FQDN"
            )
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

    resolved_ips = _resolve_host_ips(normalized)
    # Suffix 一致ホストはオンプレ向けに RFC1918 プライベート IP を許可する。
    # メタデータ / ループバック / リンクローカル等は常に拒否。
    for resolved_ip in resolved_ips:
        if suffixes:
            if (
                str(resolved_ip) in _BLOCKED_IP_LITERALS
                or resolved_ip.is_loopback
                or resolved_ip.is_link_local
                or resolved_ip.is_multicast
                or resolved_ip.is_reserved
                or resolved_ip.is_unspecified
            ):
                raise ValueError(
                    "host DNS resolution points to a blocked IP range "
                    "(loopback, link-local, metadata, or reserved)"
                )
        elif _is_blocked_ip(resolved_ip):
            raise ValueError(
                "host DNS resolution points to a blocked IP range "
                "(private, loopback, link-local, or metadata)"
            )

    return normalized
