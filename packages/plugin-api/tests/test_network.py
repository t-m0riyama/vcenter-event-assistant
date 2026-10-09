"""SSH の接続先の検証（監査 M-3、Issue #237）。

名前のまま接続すると、検証の後にもう一度名前解決が起き、ループバックやメタデータの
アドレスに接続させられる（DNS rebinding）。解決して検証した IP に接続するための関数。
"""

from __future__ import annotations

import socket

import pytest

from vcenter_event_assistant_plugin_api import network
from vcenter_event_assistant_plugin_api.network import check_ssh_address, resolve_ssh_address


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.10.0.1",
        "::1",
        "169.254.169.254",
        "169.254.1.1",
        "fe80::1",
        "224.0.0.1",
        "ff02::1",
        "240.0.0.1",
        "0.0.0.0",
        "::",
        "fd00:ec2::254",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
    ],
)
def test_rejects_addresses_that_reach_the_host_itself_or_metadata(address: str) -> None:
    with pytest.raises(ValueError):
        check_ssh_address(address)


@pytest.mark.parametrize(
    "address",
    ["10.0.0.1", "172.16.0.1", "192.168.1.1", "fd12:3456::1", "8.8.8.8", "2001:db8::1", "::ffff:10.0.0.1"],
)
def test_allows_private_and_global_addresses(address: str) -> None:
    # ESXi などのアプライアンスはプライベートな IP が普通なので、RFC1918 と ULA は許す。
    assert check_ssh_address(address) == address


def test_rejects_values_that_are_not_ip_addresses() -> None:
    with pytest.raises(ValueError):
        check_ssh_address("esxi.example.com")


def _answers(*addresses: str):
    infos = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sockaddr = (address, 22, 0, 0) if family == socket.AF_INET6 else (address, 22)
        infos.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
    return infos


@pytest.fixture
def resolver(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, int]] = []
    answers: list[list] = []

    async def fake_getaddrinfo(host: str, port: int):
        calls.append((host, port))
        if not answers:
            raise socket.gaierror(socket.EAI_NONAME, "not found")
        return answers.pop(0)

    monkeypatch.setattr(network, "_getaddrinfo", fake_getaddrinfo)
    return calls, answers


async def test_resolves_a_name_and_returns_the_checked_address(resolver) -> None:
    calls, answers = resolver
    answers.append(_answers("192.168.10.5"))
    assert await resolve_ssh_address("esxi.example.com", 2222) == "192.168.10.5"
    assert calls == [("esxi.example.com", 2222)]


async def test_rejects_a_name_that_resolves_to_loopback(resolver) -> None:
    _, answers = resolver
    answers.append(_answers("127.0.0.1"))
    with pytest.raises(ValueError):
        await resolve_ssh_address("127.0.0.1.nip.io", 22)


async def test_rejects_when_any_answer_is_blocked(resolver) -> None:
    # 接続側がどの答えを使うか分からないので、1 つでも危ない答えがあれば拒否する。
    _, answers = resolver
    answers.append(_answers("10.0.0.5", "169.254.169.254"))
    with pytest.raises(ValueError):
        await resolve_ssh_address("esxi.example.com", 22)


async def test_rejects_names_that_do_not_resolve(resolver) -> None:
    with pytest.raises(ValueError):
        await resolve_ssh_address("missing.example.com", 22)


async def test_ip_literals_are_checked_without_resolving(resolver) -> None:
    calls, _ = resolver
    assert await resolve_ssh_address("10.1.2.3", 22) == "10.1.2.3"
    assert await resolve_ssh_address("[fd12::1]", 22) == "fd12::1"
    with pytest.raises(ValueError):
        await resolve_ssh_address("127.0.0.1", 22)
    assert calls == []
