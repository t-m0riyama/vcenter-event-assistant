"""SSH などの接続先を、名前解決した後の IP で検証するヘルパ。

接続先の名前を検証してから名前のまま接続すると、接続のときにもう一度名前解決が起きる。
DNS の応答を操作できる攻撃者は、検証にはまともな IP を、接続にはループバックや
クラウドのメタデータのアドレスを返せる（DNS rebinding）。:func:`resolve_ssh_address` で
解決と検証を 1 回で済ませ、返った IP に接続すること（ホスト鍵の照合は元のホスト名で行う。
asyncssh なら ``host_key_alias``）。

ESXi などのアプライアンスはプライベートな IP で動くのが普通なので、RFC1918 と IPv6 の
ULA は許す。拒否するのは、接続元のホスト自身やクラウドの基盤に届くアドレスだけである。
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any

__all__ = ["check_ssh_address", "resolve_ssh_address"]

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# 範囲の判定（リンクローカルなど）に入らない、既知のメタデータのアドレス。
_BLOCKED_ADDRESSES = frozenset({ipaddress.ip_address("fd00:ec2::254")})


def _blocked_reason(address: IPAddress) -> str | None:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address in _BLOCKED_ADDRESSES:
        return "cloud metadata"
    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link-local or cloud metadata"
    if address.is_multicast:
        return "multicast"
    if address.is_unspecified:
        return "unspecified"
    if address.is_reserved:
        return "reserved"
    return None


def check_ssh_address(address: str) -> str:
    """IP アドレスの文字列が接続してよい宛先か確かめ、そのまま返す。

    ループバック・リンクローカル（メタデータの ``169.254.169.254`` を含む）・マルチキャスト・
    未指定・予約済みと、IPv4 射影の IPv6 で表したそれらを拒否する。

    Raises:
        ValueError: IP アドレスでないか、拒否する宛先のとき。
    """
    parsed = ipaddress.ip_address(address)
    reason = _blocked_reason(parsed)
    if reason is not None:
        raise ValueError(f"connections to {reason} addresses are not allowed")
    return address


async def _getaddrinfo(host: str, port: int) -> list[tuple[Any, ...]]:
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)


async def resolve_ssh_address(host: str, port: int) -> str:
    """接続先を名前解決して検証し、接続に使う IP アドレスを返す。

    IP アドレスならそのまま検証する（``[fd12::1]`` の角括弧は外す）。名前なら解決し、答えの
    **すべて**を検証して、1 つでも拒否する宛先があれば拒否する。返すのは最初の答え。

    Raises:
        ValueError: 解決できないか、拒否する宛先に解決されるとき。
    """
    literal = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(literal)
    except ValueError:
        pass
    else:
        return check_ssh_address(literal)
    try:
        infos = await _getaddrinfo(host, port)
    except (socket.gaierror, UnicodeError) as exc:
        raise ValueError(f"host could not be resolved: {host}") from exc
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ValueError(f"host could not be resolved: {host}")
    for address in addresses:
        try:
            check_ssh_address(address)
        except ValueError as exc:
            raise ValueError(f"{host} resolves to an address that is not allowed: {exc}") from None
    return addresses[0]
