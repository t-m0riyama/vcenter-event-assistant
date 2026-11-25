"""診断ワーカーの再検証、SSH 処理と通信路の再起動を検証する。"""

import asyncio
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import asyncssh
import pytest

from vcenter_event_assistant import process_hardening
from vcenter_event_assistant.plugins import worker
from vcenter_event_assistant.plugins.remote import CollectorWorker, CollectorWorkerError
from vcenter_event_assistant.services.diagnostics import ssh
from vcenter_event_assistant.services.diagnostics.catalog import (
    BUILTIN_COMMANDS,
    render_command,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def payload():
    return {
        "op": "diagnose",
        "ssh": {
            "host": "esx.example.net",
            "port": 2222,
            "username": "admin",
            "private_key": "key",
            "host_key": "host-key",
        },
        "deadline_seconds": 1,
        "product": "esxi",
        "command": {"builtin": "esxi.hostname", "params": {}},
    }


@pytest.mark.parametrize(
    "command",
    [
        {"builtin": "esxi.ping", "params": {"vmk": "vmk0;", "ipv4": "192.0.2.1"}},
        {"builtin": "esxi.unknown", "params": {}},
        {"builtin": "vcenter.disk", "params": {}},
        {
            "custom": {
                "template": "echo ${{x}}",
                "param_definitions": [{"name": "x", "type": "device"}],
            },
            "params": {"x": "HOME"},
        },
        {
            "custom": {
                "template": "echo {{nic}}",
                "param_definitions": [{"name": "nic", "type": "vmnic"}],
            },
            "params": {"nic": "vmnic0\n"},
        },
    ],
)
async def test_diagnostics_worker_revalidates_before_connect(
    monkeypatch, payload, command
):
    connect = AsyncMock(return_value=ssh.DiagnosticResult(executed=True, exit_status=0))
    monkeypatch.setattr(ssh, "run_ssh", connect)
    result = await worker._handle(Mock(), {**payload, "command": command})
    connect.assert_not_awaited()
    assert result["error_code"] == "invalid_command"
    assert result["executed"] is False


@pytest.mark.parametrize("command_id", [*BUILTIN_COMMANDS, "custom"])
async def test_diagnostics_worker_and_app_render_same_line(
    monkeypatch, payload, command_id
):
    values = {"vmk": "vmk0", "vmnic": "vmnic0", "ipv4": "192.0.2.1", "device": "naa.12"}
    if command_id == "custom":
        template = "esxcli network nic stats get --nic-name={{nic}}"
        definitions = [{"name": "nic", "type": "vmnic"}]
        params = {"nic": "vmnic0"}
        command = {
            "custom": {"template": template, "param_definitions": definitions},
            "params": params,
        }
        product = "esxi"
    else:
        builtin = BUILTIN_COMMANDS[command_id]
        template, definitions, product = (
            builtin.template,
            builtin.param_definitions,
            builtin.product,
        )
        params = {p["name"]: values[p["type"]] for p in definitions}
        command = {"builtin": command_id, "params": params}
    execute = AsyncMock(return_value=ssh.DiagnosticResult(executed=True, exit_status=0))
    monkeypatch.setattr(ssh, "run_ssh", execute)
    await worker._handle(Mock(), {**payload, "command": command, "product": product})
    assert execute.call_args.args[2] == render_command(template, definitions, params)


@pytest.mark.parametrize("prctl_result, expected", [(0, True), (-1, False)])
async def test_diagnostics_harden_runs_without_plugin(
    monkeypatch, prctl_result, expected
):
    monkeypatch.setattr(process_hardening, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(process_hardening.ctypes.util, "find_library", lambda _: "libc")
    prctl = Mock(return_value=prctl_result)
    monkeypatch.setattr(
        process_hardening.ctypes, "CDLL", lambda *_, **__: SimpleNamespace(prctl=prctl)
    )
    host = Mock()
    assert await worker._handle(host, {"op": "harden"}) == {"applied": expected}
    prctl.assert_called_once_with(4, 0, 0, 0, 0)
    host.load.assert_not_called()


@pytest.mark.parametrize("separated", [False, True])
async def test_diagnostics_worker_does_not_restart_after_harden(monkeypatch, separated):
    instance = CollectorWorker([], label="diagnostics")
    reader = SimpleNamespace(
        at_eof=Mock(return_value=False),
        readline=AsyncMock(
            return_value=b'{"id": 1, "ok": true, "result": {"applied": true}}\n'
        ),
    )
    writer = SimpleNamespace(
        write=Mock(), drain=AsyncMock(), is_closing=Mock(return_value=False)
    )
    proc = SimpleNamespace(returncode=None, stdin=writer, stdout=reader)
    if separated:
        instance._streams = reader, writer
    else:
        instance._process = proc
    ensure_started = AsyncMock()
    monkeypatch.setattr(instance, "ensure_started", ensure_started)
    assert await instance.request({"op": "harden"}, timeout=1) == {"applied": True}
    if separated:
        reader.at_eof.return_value = True
    else:
        proc.returncode = 1
    with pytest.raises(CollectorWorkerError, match="not running"):
        await instance.request(
            {"op": "diagnose", "ssh": {"private_key": "key"}},
            timeout=1,
            auto_start=False,
        )
    assert writer.write.call_count == 1
    assert ensure_started.await_count == 1

    # 通常の呼び出しには、自動起動の契約が引き続き適用される。
    reader.readline.return_value = b'{"id": 2, "ok": true, "result": {"ok": true}}\n'
    assert await instance.request({"op": "ping"}, timeout=1) == {"ok": True}
    assert ensure_started.await_count == 2


class ByteStream:
    def __init__(self, chunks, *, wait=False):
        self.chunks = iter(chunks)
        self.wait = wait
        self.eof = False

    async def read(self, _size):
        chunk = next(self.chunks, None)
        if chunk is not None:
            return chunk
        if self.wait:
            await asyncio.Event().wait()
        self.eof = True
        return b""


def fake_process(stdout=(), stderr=(), *, status=0, wait=False):
    return SimpleNamespace(
        stdout=ByteStream(stdout, wait=wait),
        stderr=ByteStream(stderr, wait=wait),
        stdin=Mock(),
        exit_status=status,
        wait_closed=AsyncMock(),
    )


@pytest.fixture
def connect(monkeypatch, payload):
    private_key = asyncssh.generate_private_key("ssh-ed25519")
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    payload["ssh"]["private_key"] = private_key.export_private_key().decode()
    payload["ssh"]["host_key"] = host_key.export_public_key().decode()
    connect = AsyncMock()
    monkeypatch.setattr(ssh.asyncssh, "connect", connect)
    monkeypatch.setattr(ssh, "resolve_ssh_address", AsyncMock(return_value="192.0.2.1"))
    return connect, private_key, host_key


async def test_diagnostics_ssh_keys_stay_in_memory_and_output_is_drained(
    monkeypatch, payload, connect, tmp_path
):
    connection, private_key, host_key = connect
    cwd, temp = tmp_path / "work", tmp_path / "temp"
    cwd.mkdir()
    temp.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("TMPDIR", str(temp))
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    reject_temp_file = Mock(
        side_effect=AssertionError("診断で鍵や known_hosts の一時ファイルを作成しない")
    )
    for name in (
        "mktemp",
        "mkstemp",
        "mkdtemp",
        "NamedTemporaryFile",
        "TemporaryFile",
        "SpooledTemporaryFile",
        "TemporaryDirectory",
    ):
        monkeypatch.setattr(tempfile, name, reject_temp_file)
    process = fake_process(
        [b"\xff" + b"a" * 65_535, b"discard"],
        [b"b" * 16_384, b"discard"],
        status=3,
    )
    remote = SimpleNamespace(
        create_process=AsyncMock(return_value=process), abort=Mock()
    )
    connection.return_value = remote
    result = ssh.DiagnosticResult.model_validate(await worker._handle(Mock(), payload))
    (address,) = connection.call_args.args
    options = connection.call_args.kwargs
    assert address == "192.0.2.1"
    assert options["host_key_alias"] == "esx.example.net"
    assert options["port"] == 2222
    assert (
        options["client_keys"][0].export_public_key() == private_key.export_public_key()
    )
    assert options["known_hosts"].match("esx.example.net", address, 2222)[0] == [
        host_key.convert_to_public()
    ]
    assert options["known_hosts"].match("esx.example.net", address, 22)[0] == []
    assert options["config"] is None and options["agent_path"] is None
    assert not options["password_auth"] and not options["kbdint_auth"]
    assert result.stdout == "\ufffd" + "a" * 65_535
    assert result.stderr == "b" * 16_384
    assert result.stdout_truncated and result.stderr_truncated
    assert result.executed and result.exit_status == 3 and result.status == "failed"
    assert process.stdout.eof and process.stderr.eof
    remote.abort.assert_called_once()
    reject_temp_file.assert_not_called()
    key_bytes = payload["ssh"]["private_key"].encode()
    host_key_bytes = payload["ssh"]["host_key"].strip().encode()
    for path in tmp_path.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert key_bytes not in content and host_key_bytes not in content


async def test_diagnostics_ssh_timeout_keeps_partial_output(payload, connect):
    connection, *_ = connect
    process = fake_process([b"start"], [b"x" * (ssh.STDERR_LIMIT + 1)], wait=True)
    connection.return_value = SimpleNamespace(
        create_process=AsyncMock(return_value=process), abort=Mock()
    )
    result = await worker._handle(Mock(), {**payload, "deadline_seconds": 0.03})
    assert result["error_code"] == "timeout" and result["executed"] is True
    assert result["stdout"] == "start" and result["stderr_truncated"]
    assert result["exit_status"] is None


@pytest.mark.parametrize(
    "exception, code",
    [
        (OSError("internal details"), "connect_failed"),
        (asyncssh.HostKeyNotVerifiable("internal details"), "host_key_mismatch"),
        (asyncssh.PermissionDenied("internal details"), "auth_failed"),
    ],
)
async def test_diagnostics_ssh_failure_before_execution(
    payload, connect, exception, code
):
    connection, *_ = connect
    connection.side_effect = exception
    result = await ssh.diagnose(payload)
    assert result.status == "error" and result.error_code == code
    assert (
        result.executed is False and "internal details" not in result.model_dump_json()
    )


@pytest.mark.parametrize("shell_available", [False, True])
async def test_diagnostics_vcenter_probes_shell_then_runs_command(
    payload, connect, shell_available
):
    connection, *_ = connect
    processes = [
        fake_process(status=127),
        fake_process(
            [b"VEA_REMOTE_LOG_SHELL_READY"] if shell_available else [],
            status=0,
        ),
        fake_process(status=-1),
    ]
    remote = SimpleNamespace(
        create_process=AsyncMock(side_effect=processes), abort=Mock()
    )
    connection.return_value = remote
    result = await ssh.diagnose(
        {
            **payload,
            "product": "vcenter",
            "command": {"builtin": "vcenter.disk", "params": {}},
        }
    )
    commands = [call.args[0] for call in remote.create_process.call_args_list]
    assert commands[:2] == [
        "shell /bin/bash -c 'printf VEA_REMOTE_LOG_SHELL_READY'",
        "/bin/bash -c 'printf VEA_REMOTE_LOG_SHELL_READY'",
    ]
    if shell_available:
        assert (
            commands[2]
            == "/bin/bash -c 'export PATH=/usr/sbin:/usr/bin:/sbin:/bin; df -h'"
        )
        assert result.executed and result.error_code == "no_exit_status"
    else:
        assert len(commands) == 2
        assert result.executed is False and result.error_code == "shell_unavailable"


@pytest.mark.parametrize("role", ["worker", "installer", "builder"])
async def test_diagnostics_only_worker_service_hardens_at_startup(
    monkeypatch, tmp_path, role
):
    from vcenter_event_assistant.plugins import service

    monkeypatch.setenv("VEA_PLUGIN_SERVICE_SOCKET_DIR", str(tmp_path))
    monkeypatch.setattr(service, "socket_path", lambda *_: tmp_path / "service.sock")
    monkeypatch.setattr(service, "verify_local_uid", Mock())
    harden = Mock(return_value=False)
    monkeypatch.setattr(process_hardening, "make_process_non_dumpable", harden)

    async def stop_before_bind(*_, **__):
        assert harden.call_count == (1 if role == "worker" else 0)
        raise OSError("テストのため停止")

    monkeypatch.setattr(service.asyncio, "start_unix_server", stop_before_bind)
    with pytest.raises(OSError, match="テストのため停止"):
        await service._serve(role)


@pytest.mark.parametrize("stage", ["resolve", "authenticate", "exec"])
async def test_diagnostics_ssh_timeout_before_exec_is_connect_failed(
    monkeypatch, payload, connect, stage
):
    connection, *_ = connect
    waits = []

    def timeout(seconds):
        waits.append(seconds)
        # 接続期限だけを短縮し、実時間の 8 秒を待たずに打ち切る。
        return asyncio.timeout(0.01 if seconds == 8 else seconds)

    async def stall(*args, **kwargs):
        await asyncio.Event().wait()

    remote = SimpleNamespace(create_process=AsyncMock(side_effect=stall), abort=Mock())
    connection.return_value = remote
    if stage == "resolve":
        monkeypatch.setattr(ssh, "resolve_ssh_address", stall)
    elif stage == "authenticate":
        connection.side_effect = stall

    monkeypatch.setattr(
        ssh,
        "asyncio",
        SimpleNamespace(timeout=timeout),
    )
    result = await ssh.diagnose({**payload, "deadline_seconds": 0.05})
    assert waits == [0.05, 8]
    assert result.error_code == "connect_failed" and result.executed is False
    if stage == "resolve":
        connection.assert_not_awaited()
    else:
        assert connection.call_args.kwargs["connect_timeout"] == 8
        assert connection.call_args.kwargs["login_timeout"] == 8
    if stage != "exec":
        remote.create_process.assert_not_called()
