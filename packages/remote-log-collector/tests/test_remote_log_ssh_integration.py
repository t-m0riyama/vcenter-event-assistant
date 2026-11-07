"""Optional real SSH handshake and shell reads; no appliance access required."""

import asyncio
from contextlib import asynccontextmanager
import gzip
from pathlib import Path
from uuid import uuid4

import pytest

from vea_remote_log_collector import transport
from vea_remote_log_collector.config import Source
from vea_remote_log_collector.transport import RemoteOutputLimitExceeded, open_reader

asyncssh = pytest.importorskip("asyncssh")


class KeyServer(asyncssh.SSHServer):
    def __init__(self, client_key):
        self.client_key = client_key

    def begin_auth(self, username):
        return True

    def public_key_auth_supported(self):
        return True

    def validate_public_key(self, username, key):
        return (
            username == "reader"
            and key.export_public_key() == self.client_key.export_public_key()
        )


async def execute(process):
    child = await asyncio.create_subprocess_shell(
        process.command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await child.communicate()
        process.stdout.write(stdout)
        process.stderr.write(stderr)
        process.exit(child.returncode)
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()


@asynccontextmanager
async def ssh_source(tmp_path, monkeypatch, product="esxi", *, process_factory=execute, **server_options):
    server_key = asyncssh.generate_private_key("ssh-ed25519")
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    key_file = tmp_path / "id"
    key_file.write_bytes(client_key.export_private_key())
    key_file.chmod(0o600)
    server = await asyncssh.create_server(
        lambda: KeyServer(client_key),
        "127.0.0.1",
        0,
        server_host_keys=[server_key],
        process_factory=process_factory,
        encoding=None,
        **server_options,
    )
    port = server.get_port()

    # The checked address is used for the connection; loopback is rejected in
    # production, so point the name at the local server only here. The known_hosts
    # line keeps the name and a non-default port, as materialize_ssh writes it.
    async def resolve(host, resolved_port):
        assert (host, resolved_port) == ("esxi.test", port)
        return "127.0.0.1"

    monkeypatch.setattr(transport, "resolve_ssh_address", resolve)
    hosts = tmp_path / "known_hosts"
    hosts.write_bytes(f"[esxi.test]:{port} ".encode() + server_key.export_public_key())
    source = Source(
        "s", uuid4(), product, "esxi.test", port, "reader", str(key_file), str(hosts)
    )
    try:
        yield source
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("product", ["esxi", "vcenter"])
async def test_real_key_authentication_verified_host_and_binary_ranges(tmp_path, monkeypatch, product):
    data_file = tmp_path / "test.log"
    data_file.write_bytes(("日本語\n" * 100).encode())
    compressed_file = tmp_path / "test.log.gz"
    compressed_file.write_bytes(gzip.compress(data_file.read_bytes()))
    async with ssh_source(tmp_path, monkeypatch, product) as source:
        async with open_reader(source) as reader:
            data = await reader.read(str(data_file), 5, 111)
            assert data == data_file.read_bytes()[5:116]
            assert await reader.read(str(compressed_file), 5, 111) == data
            assert await reader.read(str(compressed_file), 9, 23) == data_file.read_bytes()[9:32]
            corrupt_file = tmp_path / "corrupt.log.gz"
            corrupt_file.write_bytes(b"invalid gzip data")
            with pytest.raises(asyncssh.ProcessError):
                await reader.read(str(corrupt_file), 0, 10)
        wrong_key = asyncssh.generate_private_key("ssh-ed25519")
        Path(source.known_hosts_file).write_bytes(
            f"[{source.host}]:{source.port} ".encode() + wrong_key.export_public_key()
        )
        with pytest.raises(asyncssh.HostKeyNotVerifiable):
            async with open_reader(source):
                pytest.fail("mismatched host key must never be accepted")


@pytest.mark.parametrize("stream_name", ["stdout", "stderr"])
async def test_output_limit_stops_live_command_before_it_exits(tmp_path, monkeypatch, stream_name):
    release = asyncio.Event()

    async def flood(process):
        getattr(process, stream_name).write(b"x" * (16 * 1024 + 1))
        await release.wait()

    async with ssh_source(tmp_path, monkeypatch, process_factory=flood) as source:
        try:
            async with asyncio.timeout(2):
                async with open_reader(source) as reader:
                    with pytest.raises(RemoteOutputLimitExceeded):
                        await reader.command("flood")
                    await reader.connection.wait_closed()
        finally:
            release.set()


@pytest.mark.parametrize("extended", [False, True])
async def test_peer_cannot_exceed_window_before_exec_ack(tmp_path, monkeypatch, extended):
    from asyncssh.channel import SSHServerChannel
    from asyncssh.constants import MSG_CHANNEL_DATA, MSG_CHANNEL_EXTENDED_DATA
    from asyncssh.packet import String, UInt32

    def flood_before_ack(channel, packet):
        packet.get_string()
        packet.check_end()
        chunk = b"x" * 1024
        data = String(chunk)
        # Bypass server-side flow control, and deliberately withhold the reply.
        for _ in range(transport._RECEIVE_WINDOW // len(chunk) + 1):
            if extended:
                channel.send_packet(MSG_CHANNEL_EXTENDED_DATA, UInt32(1), data)
            else:
                channel.send_packet(MSG_CHANNEL_DATA, data)
        return None

    monkeypatch.setattr(SSHServerChannel, "_process_exec_request", flood_before_ack)
    async with ssh_source(tmp_path, monkeypatch) as source:
        async with asyncio.timeout(2):
            async with open_reader(source) as reader:
                with pytest.raises(asyncssh.ProtocolError, match="Window exceeded"):
                    await reader.command("flood before exec acknowledgement")


async def test_large_binary_stdout_with_interleaved_stderr(tmp_path, monkeypatch):
    chunk = bytes(range(256)) * 1024
    count = 16

    async def output(process):
        for _ in range(count):
            process.stderr.write(b"e" * 1024)
            process.stdout.write(chunk)
            await process.stdout.drain()
        process.exit(0)

    async with ssh_source(tmp_path, monkeypatch, process_factory=output) as source:
        async with open_reader(source) as reader:
            stdout = await reader.read("/var/run/log/vmkernel.log", 0, len(chunk) * count)
            assert stdout == chunk * count


@pytest.mark.parametrize("size_mib", [1, 4])
async def test_large_range_can_continue_with_delayed_window_updates(tmp_path, monkeypatch, size_mib):
    from asyncssh.channel import SSHClientChannel
    from asyncssh.constants import MSG_CHANNEL_WINDOW_ADJUST

    send_packet = SSHClientChannel.send_packet

    def delay_window_update(channel, packet_type, *args):
        if packet_type != MSG_CHANNEL_WINDOW_ADJUST:
            send_packet(channel, packet_type, *args)
            return

        def send_if_open():
            if not channel.is_closing():
                send_packet(channel, packet_type, *args)

        asyncio.get_running_loop().call_later(0.04, send_if_open)

    data = b"x" * (size_mib * 1024 * 1024)

    async def output(process):
        process.stdout.write(data)
        process.exit(0)

    monkeypatch.setattr(SSHClientChannel, "send_packet", delay_window_update)
    monkeypatch.setattr(transport, "_COMMAND_TIMEOUT", 0.3)
    async with ssh_source(tmp_path, monkeypatch, process_factory=output) as source:
        async with asyncio.timeout(6):
            async with open_reader(source) as reader:
                assert await reader.read("/var/run/log/vmkernel.log", 0, len(data)) == data


async def test_server_cannot_require_ssh_transport_compression(tmp_path, monkeypatch):
    async with ssh_source(tmp_path, monkeypatch, compression_algs=["zlib@openssh.com"]) as source:
        with pytest.raises(asyncssh.KeyExchangeFailed):
            async with open_reader(source):
                pytest.fail("SSH transport compression must be disabled")
