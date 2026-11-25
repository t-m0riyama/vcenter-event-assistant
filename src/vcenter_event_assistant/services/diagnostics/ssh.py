"""診断ワーカーの SSH 接続と出力の取得。"""

import asyncio
import logging
import shlex
from dataclasses import dataclass, field
from typing import Literal

import asyncssh
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vcenter_event_assistant.services.diagnostics.catalog import (
    BUILTIN_COMMANDS,
    render_command,
)
from vcenter_event_assistant_plugin_api.network import resolve_ssh_address

logger = logging.getLogger(__name__)

STDOUT_LIMIT = 64 * 1024
STDERR_LIMIT = 16 * 1024
Product = Literal["esxi", "vcenter"]
ErrorCode = Literal[
    "invalid_command",
    "connect_failed",
    "host_key_mismatch",
    "auth_failed",
    "shell_unavailable",
    "no_exit_status",
    "timeout",
    "worker_unavailable",
]


class DiagnosticResult(BaseModel):
    """ワーカーの応答。出力のバイト数は UTF-8 に変換する前に数える。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    executed: bool | None
    exit_status: int | None = Field(default=None, ge=0)
    error_code: ErrorCode | None = None
    stdout: str = Field(default="", max_length=STDOUT_LIMIT, repr=False)
    stderr: str = Field(default="", max_length=STDERR_LIMIT, repr=False)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_bytes: int = Field(default=0, ge=0, le=STDOUT_LIMIT)
    stderr_bytes: int = Field(default=0, ge=0, le=STDERR_LIMIT)

    @property
    def status(self) -> Literal["succeeded", "failed", "error"]:
        if self.error_code is not None:
            return "error"
        return "succeeded" if self.exit_status == 0 else "failed"


class SSHDestination(BaseModel):
    model_config = ConfigDict(strict=True)

    host: str
    port: int = Field(ge=1, le=65535)
    username: str
    private_key: str = Field(repr=False)
    host_key: str = Field(repr=False)


class CustomCommand(BaseModel):
    model_config = ConfigDict(strict=True)

    template: str = Field(min_length=1, max_length=1000)
    param_definitions: list[dict[str, str]]


class WorkerCommand(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    builtin: str | None = None
    custom: CustomCommand | None = None
    params: dict[str, str]

    def render(self, product: Product) -> str:
        if self.builtin is not None and self.custom is None:
            command = BUILTIN_COMMANDS[self.builtin]
            if command.product != product:
                raise ValueError("コマンドの製品が対象と一致しません。")
            return render_command(
                command.template, command.param_definitions, self.params
            )
        if self.custom is not None and self.builtin is None:
            return render_command(
                self.custom.template, self.custom.param_definitions, self.params
            )
        raise ValueError("診断コマンドを 1 件指定してください。")


class DiagnoseRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    ssh: SSHDestination
    product: Product
    command: WorkerCommand
    deadline_seconds: float = Field(gt=0, le=45)


@dataclass
class Output:
    limit: int
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False

    async def drain(self, stream: asyncssh.SSHReader[bytes]) -> None:
        while chunk := await stream.read(8192):
            remaining = self.limit - len(self.data)
            self.data.extend(chunk[:remaining])
            self.truncated |= len(chunk) > remaining

    def text(self) -> str:
        # PostgreSQL の Text に NUL は保存できない。
        return self.data.decode("utf-8", errors="replace").replace("\0", "\ufffd")


async def _read_process(
    process: asyncssh.SSHClientProcess[bytes],
    stdout: Output,
    stderr: Output,
) -> int | None:
    readers = (
        asyncio.create_task(stdout.drain(process.stdout)),
        asyncio.create_task(stderr.drain(process.stderr)),
    )
    try:
        await asyncio.gather(*readers)
        await process.wait_closed()
        status = process.exit_status
        return status if status is not None and status >= 0 else None
    finally:
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)


async def _vcenter_shell(connection: asyncssh.SSHClientConnection) -> str | None:
    marker = b"VEA_REMOTE_LOG_SHELL_READY"
    probe = f"printf {marker.decode()}"
    for prefix in ("shell /bin/bash -c", "/bin/bash -c"):
        stdout, stderr = Output(4096), Output(0)
        process = await connection.create_process(
            f"{prefix} {shlex.quote(probe)}",
            encoding=None,
            window=STDOUT_LIMIT,
        )
        process.stdin.write_eof()
        status = await _read_process(process, stdout, stderr)
        if status == 0 and not stdout.truncated and stdout.data.strip() == marker:
            return prefix
    return None


async def diagnose(payload: dict[str, object]) -> DiagnosticResult:
    try:
        request = DiagnoseRequest.model_validate(payload)
        line = request.command.render(request.product)
    except (ValidationError, ValueError, KeyError):
        return DiagnosticResult(executed=False, error_code="invalid_command")
    return await run_ssh(request.ssh, request.product, line, request.deadline_seconds)


async def run_ssh(
    ssh: SSHDestination,
    product: Product,
    line: str,
    deadline_seconds: float,
) -> DiagnosticResult:
    stdout, stderr = Output(STDOUT_LIMIT), Output(STDERR_LIMIT)
    executed = False
    exit_status = None
    phase: ErrorCode = "connect_failed"
    error_code: ErrorCode | None = None
    connection = None
    try:
        async with asyncio.timeout(deadline_seconds):
            # 照合には元の名前を使い、接続には検証済みの IP だけを渡す。
            pattern = ssh.host if ssh.port == 22 else f"[{ssh.host}]:{ssh.port}"
            async with asyncio.timeout(8):
                address = await resolve_ssh_address(ssh.host, ssh.port)
                connection = await asyncssh.connect(
                    address,
                    port=ssh.port,
                    host_key_alias=ssh.host,
                    username=ssh.username,
                    client_keys=[asyncssh.import_private_key(ssh.private_key)],
                    known_hosts=asyncssh.import_known_hosts(
                        f"{pattern} {ssh.host_key.strip()}\n"
                    ),
                    agent_path=None,
                    config=None,
                    password_auth=False,
                    kbdint_auth=False,
                    compression_algs=None,
                    connect_timeout=8,
                    login_timeout=8,
                )
            if product == "vcenter":
                phase = "shell_unavailable"
                prefix = await _vcenter_shell(connection)
                if prefix is None:
                    return DiagnosticResult(executed=False, error_code=phase)
                script = "export PATH=/usr/sbin:/usr/bin:/sbin:/bin; " + line
                line = f"{prefix} {shlex.quote(script)}"
            phase = "connect_failed"
            process = await connection.create_process(
                line, encoding=None, window=STDOUT_LIMIT
            )
            executed = True
            phase = "no_exit_status"
            process.stdin.write_eof()
            exit_status = await _read_process(process, stdout, stderr)
            if exit_status is None:
                error_code = phase
    except TimeoutError:
        error_code = "timeout" if executed else phase
    except asyncssh.HostKeyNotVerifiable as exc:
        error_code = "host_key_mismatch"
        logger.warning("診断の SSH ホスト鍵を確認できません: %s", exc)
    except (asyncssh.PermissionDenied, asyncssh.KeyImportError) as exc:
        error_code = "auth_failed"
        logger.warning("診断の SSH 認証に失敗しました: %s", exc)
    except (asyncssh.Error, OSError, ValueError) as exc:
        error_code = phase
        logger.warning("診断の SSH 処理に失敗しました: %s", exc)
    finally:
        if connection is not None:
            connection.abort()
    return DiagnosticResult(
        executed=executed,
        exit_status=exit_status,
        error_code=error_code,
        stdout=stdout.text(),
        stderr=stderr.text(),
        stdout_truncated=stdout.truncated,
        stderr_truncated=stderr.truncated,
        stdout_bytes=len(stdout.data),
        stderr_bytes=len(stderr.data),
    )
