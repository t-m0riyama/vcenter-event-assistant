"""Optional real SSH handshake and shell reads; no appliance access required."""

import asyncio
import gzip

import pytest

from vea_remote_log_collector.config import Source
from vea_remote_log_collector.transport import open_reader
from uuid import uuid4

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


@pytest.mark.parametrize("product", ["esxi", "vcenter"])
async def test_real_key_authentication_verified_host_and_binary_ranges(tmp_path, product):
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
        process_factory=execute,
        encoding=None,
    )
    port = server.get_port()
    hosts = tmp_path / "known_hosts"
    hosts.write_bytes(f"[127.0.0.1]:{port} ".encode() + server_key.export_public_key())
    data_file = tmp_path / "test.log"
    data_file.write_bytes(("日本語\n" * 100).encode())
    compressed_file = tmp_path / "test.log.gz"
    compressed_file.write_bytes(gzip.compress(data_file.read_bytes()))
    source = Source(
        "s", uuid4(), product, "127.0.0.1", port, "reader", str(key_file), str(hosts)
    )
    try:
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
        hosts.write_bytes(
            f"[127.0.0.1]:{port} ".encode() + wrong_key.export_public_key()
        )
        with pytest.raises(asyncssh.HostKeyNotVerifiable):
            async with open_reader(source):
                pytest.fail("mismatched host key must never be accepted")
    finally:
        server.close()
        await server.wait_closed()
