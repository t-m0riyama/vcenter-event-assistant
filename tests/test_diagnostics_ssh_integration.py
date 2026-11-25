"""asyncssh のサーバーで、非標準ポートの鍵照合と出力の取得を検証する。"""

import asyncio
from unittest.mock import AsyncMock

import asyncssh
import pytest

from vcenter_event_assistant.services.diagnostics import ssh


class DiagnosticServer(asyncssh.SSHServer):
    def __init__(self, authorized_key):
        self.authorized_key = authorized_key

    def public_key_auth_supported(self):
        return True

    def validate_public_key(self, username, key):
        return username == "diagnostic" and key == self.authorized_key


@pytest.mark.asyncio
async def test_diagnostics_asyncssh_nondefault_port_host_key_and_output(monkeypatch):
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    server_key = asyncssh.generate_private_key("ssh-ed25519")
    resolve = AsyncMock(return_value="127.0.0.1")
    monkeypatch.setattr(ssh, "resolve_ssh_address", resolve)
    commands = []

    async def execute(process):
        commands.append(process.command)
        process.stdout.write(b"x" * (ssh.STDOUT_LIMIT * 3))
        process.stderr.write(b"e" * (ssh.STDERR_LIMIT * 2))
        await asyncio.gather(process.stdout.drain(), process.stderr.drain())
        process.exit(7)

    async with asyncssh.listen(
        "127.0.0.1",
        0,
        config=None,
        server_host_keys=[server_key],
        server_factory=lambda: DiagnosticServer(client_key.convert_to_public()),
        process_factory=execute,
        encoding=None,
    ) as listener:
        port = listener.get_port()
        assert port != 22
        destination = ssh.SSHDestination(
            host="esxi.example.test",
            port=port,
            username="diagnostic",
            host_key=server_key.export_public_key().decode(),
            private_key=client_key.export_private_key().decode(),
        )
        result = await ssh.run_ssh(destination, "esxi", "esxcli system hostname get", 5)
        assert result.executed and result.exit_status == 7 and result.status == "failed"
        assert result.stdout == "x" * ssh.STDOUT_LIMIT and result.stdout_truncated
        assert result.stderr == "e" * ssh.STDERR_LIMIT and result.stderr_truncated

        untrusted_key = (
            asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
        )
        mismatch = await ssh.run_ssh(
            destination.model_copy(update={"host_key": untrusted_key}),
            "esxi",
            "esxcli system hostname get",
            5,
        )
        assert mismatch.error_code == "host_key_mismatch" and mismatch.executed is False
    assert commands == ["esxcli system hostname get"]
    resolve.assert_awaited_with("esxi.example.test", port)
