from types import SimpleNamespace
import shlex
import sys
from uuid import uuid4

import pytest

from vea_remote_log_collector import transport
from vea_remote_log_collector.config import Source, sources_from_config
from vea_remote_log_collector.transport import LogFileChanged, RemoteFile, SSHReader, ShellAccessError, open_reader


def source(product="esxi"):
    return Source(
        "s", uuid4(), product, "host.local", 22, "reader", "/keys/id", "/keys/hosts"
    )


def _resolve_to(address):
    async def resolve(host, port):
        return address
    return resolve


class Connection:
    def __init__(self, outputs=()):
        self.outputs = iter(outputs)
        self.commands = []

    async def run(self, command, **kwargs):
        self.commands.append(command)
        assert kwargs == {"encoding": None, "check": True, "timeout": 8}
        if "printf VEA_REMOTE_LOG_SHELL_READY" in command:
            return SimpleNamespace(stdout=b"VEA_REMOTE_LOG_SHELL_READY")
        return SimpleNamespace(stdout=next(self.outputs, b""))


async def test_esxi_fixed_presets_and_rotation_names():
    conn = Connection(
        [
            b"1:2 10 100 /var/run/log/vmkernel.log\n1:3 5 90 /var/run/log/vmkernel.1.gz\n",
            b"0123456789",
            b"5\n",
            b"abcde",
        ]
    )
    files = await SSHReader(conn, source()).files("vmkernel", {"files": []})
    assert [f.path for f in files] == [
        "/var/run/log/vmkernel.1.gz",
        "/var/run/log/vmkernel.log",
    ]
    assert files[0].size == 5
    assert "stat -L -c" in conn.commands[0]
    assert "gzip -t" in conn.commands[2]


async def test_bootstrap_and_completed_archive_only_stat_historical_gzip():
    listing = b"1:2 10 100 /var/run/log/vmkernel.log\n1:3 5 90 /var/run/log/vmkernel.1.gz\n"
    conn = Connection([listing, b"0123456789"])
    files = await SSHReader(conn, source()).files("vmkernel")
    archive = files[0]
    assert archive.metadata_only and archive.size == 0
    assert len(conn.commands) == 2
    assert all("gzip" not in command for command in conn.commands)
    previous = {"files": [{"identity": "1:3", "disk_size": 5, "modified": 90, "offset": 0, "done": True}]}
    conn = Connection([listing, b"0123456789"])
    files = await SSHReader(conn, source()).files("vmkernel", previous)
    assert files[0].metadata_only
    assert len(conn.commands) == 2
    assert all("gzip" not in command for command in conn.commands)


async def test_changed_archive_is_inspected_and_gzip_validated_once():
    listing = b"1:2 10 100 /var/run/log/vmkernel.log\n1:3 5 91 /var/run/log/vmkernel.1.gz\n"
    previous = {"files": [{"identity": "1:3", "disk_size": 5, "modified": 90, "offset": 0, "done": True}]}
    conn = Connection([listing, b"0123456789", b"5\n", b"abcde", b"ab"])
    reader = SSHReader(conn, source())
    files = await reader.files("vmkernel", previous)
    assert not files[0].metadata_only and files[0].prefix == b"abcde"
    assert await reader.read(files[0].path, 0, 2) == b"ab"
    assert sum("gzip -t" in command for command in conn.commands) == 1


async def test_vcenter_appliance_shell_uses_read_command_without_changing_shell():
    conn = Connection([b"abc"])
    reader = SSHReader(conn, source("vcenter"))
    assert await reader.read("/var/log/vmware/vpxd/vpxd.log", 4096, 3) == b"abc"
    command = conn.commands[-1]
    assert shlex.split(command)[:3] == ["shell", "/bin/bash", "-c"]
    script = shlex.split(command)[3]
    assert "tail -c +4097 /var/log/vmware/vpxd/vpxd.log" in script
    assert "head -c 3" in script
    assert "chsh" not in command


async def test_vcenter_bash_login_uses_direct_bash_and_remembers_detection():
    import asyncssh

    class BashConnection(Connection):
        async def run(self, command, **kwargs):
            if command.startswith("shell "):
                self.commands.append(command)
                raise asyncssh.ProcessError(None, command, None, 127, None, 127, b"", b"shell: not found")
            return await super().run(command, **kwargs)

    conn = BashConnection([b"/usr/bin/stat\n", b"10\n"])
    reader = SSHReader(conn, source("vcenter"))
    assert await reader.command("command -v stat") == b"/usr/bin/stat\n"
    assert await reader.command("stat -c '%s' /var/log/vmware/vpxd/vpxd.log") == b"10\n"
    assert len(conn.commands) == 4  # two probes, two reads
    assert all(c.startswith("/bin/bash -c ") for c in conn.commands[1:])
    assert "export PATH=/usr/sbin:/usr/bin:/sbin:/bin" in conn.commands[-1]
    assert all("chsh" not in c and "shell.set" not in c for c in conn.commands)


async def test_vcenter_disabled_bash_fails_before_log_command():
    import asyncssh

    class DisabledConnection(Connection):
        async def run(self, command, **kwargs):
            self.commands.append(command)
            raise asyncssh.ProcessError(None, command, None, 1, None, 1, b"", b"unavailable")

    conn = DisabledConnection()
    with pytest.raises(ShellAccessError):
        await SSHReader(conn, source("vcenter")).command("command -v stat")
    assert len(conn.commands) == 2
    assert all("command -v stat" not in c for c in conn.commands)


async def test_snapshot_change_is_rejected():
    conn = Connection([b"different-inode 100 100"])
    with pytest.raises(ValueError, match="rotated"):
        await SSHReader(conn, source()).verify(
            RemoteFile("/var/run/log/vmkernel.log", "inode", 20, 100, b"", True, 20)
        )


async def test_vcenter_active_symlink_alias_is_not_treated_as_archive():
    conn = Connection([
        b"1:2 100 100 /var/log/vmware/vpxd/vpxd.log\n"
        b"1:2 110 101 /var/log/vmware/vpxd/vpxd-20.log\n"
        b"1:3 80 90 /var/log/vmware/vpxd/vpxd-19.log.gz\n",
        b"x" * 100,
        b"1:2 120 102\n",
        b"1:4 100 103\n",
    ])
    reader = SSHReader(conn, source("vcenter"))
    files = await reader.files("vpxd")
    assert [f.path for f in files] == [
        "/var/log/vmware/vpxd/vpxd-19.log.gz", "/var/log/vmware/vpxd/vpxd.log",
    ]
    active = files[-1]
    assert active.size == 100
    await reader.verify(active)  # normal append and mtime change
    with pytest.raises(LogFileChanged):
        await reader.verify(active)  # link now points to a different inode
    assert all("stat -L -c" in command for command in conn.commands if "stat " in command)


async def test_ssh_connection_uses_only_explicit_keys_and_strict_host_verification(
    monkeypatch,
):
    options = {}
    closed = []

    class Context:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *args):
            closed.append(True)

    def connect(host, **kwargs):
        options.update(kwargs)
        options["host"] = host
        return Context()

    monkeypatch.setitem(sys.modules, "asyncssh", SimpleNamespace(connect=connect))
    monkeypatch.setattr(transport, "resolve_ssh_address", _resolve_to("192.0.2.10"))
    async with open_reader(source()):
        pass
    assert options["known_hosts"] == "/keys/hosts"
    assert options["client_keys"] == ["/keys/id"]
    assert options["agent_path"] is None
    assert options["password_auth"] is False
    assert options["kbdint_auth"] is False
    assert closed



def _capture_connect(monkeypatch):
    calls = []

    class Context:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *args):
            return None

    def connect(host, **kwargs):
        calls.append({"host": host, **kwargs})
        return Context()

    monkeypatch.setitem(sys.modules, "asyncssh", SimpleNamespace(connect=connect))
    return calls


async def test_connects_to_the_checked_address_even_if_dns_answers_change(monkeypatch):
    # 監査 M-3（Issue #237）。名前のまま接続すると、asyncssh がもう一度名前解決し、
    # 2 回目の答え（ループバック）に接続してしまう（DNS rebinding）。
    import socket

    from vcenter_event_assistant_plugin_api import network

    answers = [["10.0.0.5"], ["127.0.0.1"]]

    async def getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answers.pop(0)[0], port))]

    monkeypatch.setattr(network, "_getaddrinfo", getaddrinfo)
    calls = _capture_connect(monkeypatch)
    async with open_reader(Source("s", uuid4(), "esxi", "esxi.example.com", 2222, "reader", "/k", "/h")):
        pass
    assert len(calls) == 1
    assert calls[0]["host"] == "10.0.0.5"
    assert calls[0]["port"] == 2222
    # ホスト鍵は元のホスト名で照合する（known_hosts は [esxi.example.com]:2222 の行）。
    assert calls[0]["host_key_alias"] == "esxi.example.com"


async def test_does_not_connect_to_a_name_that_resolves_to_a_blocked_address(monkeypatch):
    async def resolve(host, port):
        raise ValueError("blocked")

    monkeypatch.setattr(transport, "resolve_ssh_address", resolve)
    calls = _capture_connect(monkeypatch)
    with pytest.raises(ValueError):
        async with open_reader(source()):
            pass
    assert calls == []


def test_config_requires_stable_ids_key_files_and_known_hosts(tmp_path):
    key = tmp_path / "id"
    hosts = tmp_path / "hosts"
    key.write_text("key")
    hosts.write_text("known host")
    item = {
        "id": "esxi-1",
        "vcenter_id": str(uuid4()),
        "product": "esxi",
        "host": "host.local",
        "username": "reader",
        "private_key_file": str(key),
        "known_hosts_file": str(hosts),
    }
    assert sources_from_config({"sources": [item]})[0].port == 22
    with pytest.raises(ValueError):
        sources_from_config({"sources": [item, item]})
    item["known_hosts_file"] = ""
    with pytest.raises(ValueError):
        sources_from_config({"sources": [item]})
