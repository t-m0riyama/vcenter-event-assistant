"""Run one non-root Linux service for plugin execution, installation, or building."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import shutil
import signal
import socket
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

from vcenter_event_assistant.plugins.installer import (
    INSTALL_TIMEOUT_SECONDS,
    MAX_UPLOAD_BYTES,
    parse_requirement,
    parse_upload_filename,
)
from vcenter_event_assistant.plugins.service_protocol import (
    ARTIFACT_LIMIT,
    CHUNK_SIZE,
    FILE_LIMIT,
    HEADER_LIMIT,
    WORKER_SESSION_READY,
    WORKER_SESSION_UNAVAILABLE,
    PluginServiceError,
    encode_header,
    read_header,
    socket_path,
    verify_local_uid,
    verify_peer,
)
from vcenter_event_assistant.plugins.subprocess_env import (
    IGNORE_DOTENV_ENV_VAR,
    INSTALLER_JOB_ENV_VARS,
    PROXY_ENV_VARS,
    ROLE_LOCAL_TLS_ENV,
    installer_env,
    url_has_credentials,
)
from vcenter_event_assistant.plugins.wire import MAX_REQUEST_BYTES

_WORKER_MODULE = "vcenter_event_assistant.plugins.worker"
_SUPERVISOR = Path(__file__).with_name("process_supervisor.py")
logger = logging.getLogger(__name__)


class WorkerSessionError(PluginServiceError):
    """The service could not create a worker session."""


def _supervised(*command: str) -> tuple[str, ...]:
    return (sys.executable, "-I", str(_SUPERVISOR), *command)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    # Let the subreaper terminate and reap the job before removing its files.
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        async with asyncio.timeout(5):
            if process.stdout is not None:
                await process.stdout.read()
            await process.wait()
    except TimeoutError:
        logger.warning("plugin process supervisor did not finish cleanup")
        with contextlib.suppress(ProcessLookupError):
            process.kill()


async def _copy_pipe(
    source: asyncio.StreamReader, target: asyncio.StreamWriter
) -> None:
    while chunk := await source.read(CHUNK_SIZE):
        target.write(chunk)
        await target.drain()


async def _read_worker_requests(
    reader: asyncio.StreamReader, pending: asyncio.Queue[bytes],
) -> None:
    while line := await reader.readline():
        if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n") or pending.full():
            raise PluginServiceError("invalid worker request frame")
        pending.put_nowait(line)


async def _write_worker_requests(
    stdin: asyncio.StreamWriter, pending: asyncio.Queue[bytes],
) -> None:
    while True:
        stdin.write(await pending.get())
        await stdin.drain()


async def _worker(
    request: dict[str, Any], reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    root = Path(os.environ["VEA_PLUGIN_DIR"]).resolve()
    paths = request["paths"]
    if not isinstance(paths, list) or not all(
        isinstance(path, str)
        and Path(path).resolve().is_relative_to(root)
        and Path(path).is_dir()
        for path in paths
    ):
        raise PluginServiceError("invalid plugin paths")
    env = request["env"]
    if not isinstance(env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in env.items()
    ):
        raise PluginServiceError("invalid worker environment")
    for key in (
        "HOME", "PATH", "TMPDIR", "TMP", "TEMP", "USER", "LOGNAME", "VIRTUAL_ENV",
        "PYTHONPATH", *ROLE_LOCAL_TLS_ENV,
    ):
        env.pop(key, None)
        if key in os.environ:
            env[key] = os.environ[key]
    env[IGNORE_DOTENV_ENV_VAR] = "1"
    command = [sys.executable, "-m", _WORKER_MODULE]
    for path in paths:
        command.extend(("--plugin-path", path))
    try:
        directory = tempfile.TemporaryDirectory(prefix="worker-session-", dir=os.environ["TMPDIR"])
    except OSError as exc:
        raise WorkerSessionError("worker temporary directory unavailable") from exc
    with directory as tmp:
        env["TMPDIR"] = tmp
        await _run_worker(command, env, reader, writer)


async def _run_worker(
    command: list[str], env: dict[str, str],
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
) -> None:
    process = await _spawn_worker(command, env)
    try:
        _write_frame(writer, WORKER_SESSION_READY)
        await writer.drain()
        await _relay_worker(process, reader, writer)
    finally:
        assert process.stdin is not None
        process.stdin.transport.abort()
        await _stop_process(process)


async def _spawn_worker(command: list[str], env: dict[str, str]) -> asyncio.subprocess.Process:
    process = None
    try:
        with contextlib.ExitStack() as stack:
            receive, notify = socket.socketpair()
            stack.enter_context(receive)
            stack.enter_context(notify)
            receive.setblocking(False)
            process = await asyncio.create_subprocess_exec(
                *_supervised(f"--ready-fd={notify.fileno()}", *command),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                env=env, start_new_session=True, pass_fds=(notify.fileno(),),
            )
            notify.close()
            async with asyncio.timeout(5):
                if await asyncio.get_running_loop().sock_recv(receive, 1) != b"1":
                    raise WorkerSessionError("worker supervisor could not start the child")
            return process
    except (OSError, WorkerSessionError, asyncio.CancelledError) as exc:
        if process is not None:
            await _stop_process(process)
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise WorkerSessionError("worker session unavailable") from exc


async def _relay_worker(
    process: asyncio.subprocess.Process, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
) -> None:
    assert process.stdin is not None and process.stdout is not None
    pending: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    relays = (
        asyncio.create_task(_read_worker_requests(reader, pending)),
        asyncio.create_task(_write_worker_requests(process.stdin, pending)),
        asyncio.create_task(_copy_pipe(process.stdout, writer)),
    )
    try:
        done, _ = await asyncio.wait(relays, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for relay in relays:
            relay.cancel()
        await asyncio.gather(*relays, return_exceptions=True)


def _write_frame(writer: asyncio.StreamWriter, value: dict[str, Any]) -> None:
    writer.write(encode_header(value))


async def _send_artifact(target: Path, writer: asyncio.StreamWriter) -> None:
    total = count = 0
    for parent, dirs, files in os.walk(target, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(parent) / name
            info = path.lstat()
            count += 1
            if count > FILE_LIMIT:
                raise PluginServiceError("plugin artifact has too many entries")
            relative = path.relative_to(target).as_posix()
            if stat.S_ISDIR(info.st_mode):
                _write_frame(writer, {"directory": relative})
                await writer.drain()
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PluginServiceError("plugin artifact contains unsupported files")
            total += info.st_size
            if total > ARTIFACT_LIMIT:
                raise PluginServiceError("plugin artifact is too large")
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
                opened = os.fstat(source.fileno())
                if not stat.S_ISREG(opened.st_mode) or opened.st_size != info.st_size:
                    raise PluginServiceError("plugin artifact changed during transfer")
                _write_frame(writer, {"file": relative, "size": opened.st_size,
                                      "executable": bool(opened.st_mode & stat.S_IXUSR)})
                remaining = opened.st_size
                while remaining:
                    data = source.read(min(remaining, CHUNK_SIZE))
                    if not data:
                        raise PluginServiceError("plugin artifact changed during transfer")
                    remaining -= len(data)
                    writer.write(data)
                    await writer.drain()
            await writer.drain()
    _write_frame(writer, {"complete": True})
    await writer.drain()


async def _install(
    role: str, request: dict[str, Any], reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter, work: Path,
) -> None:
    source = request["source"]
    from_index = request["from_index"]
    if not isinstance(source, str) or type(from_index) is not bool:
        raise PluginServiceError("invalid install source")
    if from_index:
        parse_requirement(source)
    else:
        parse_upload_filename(source)
        if role == "installer" and not source.endswith(".whl"):
            raise PluginServiceError("wheel installer requires a wheel")
        size = request["size"]
        if type(size) is not int or not 0 < size <= MAX_UPLOAD_BYTES:
            raise PluginServiceError("invalid upload size")
        upload = work / "upload"
        upload.mkdir()
        with (upload / source).open("xb") as package:
            while size:
                chunk = await reader.readexactly(min(size, CHUNK_SIZE))
                package.write(chunk)
                size -= len(chunk)
        source = str(upload / source)

    index = request["index"]
    if index is not None and not isinstance(index, str):
        raise PluginServiceError("invalid plugin index")
    proxies = request["proxies"]
    if not isinstance(proxies, dict) or any(
        key not in (*PROXY_ENV_VARS, "NO_PROXY", "no_proxy") or not isinstance(value, str)
        for key, value in proxies.items()
    ):
        raise PluginServiceError("invalid plugin proxy configuration")
    if role == "builder" and (url_has_credentials(index) or any(
        url_has_credentials(value) for value in proxies.values()
    )):
        raise PluginServiceError("builder cannot receive index or proxy credentials")
    uv_options = request["uv_options"]
    if not isinstance(uv_options, dict) or any(
        key not in INSTALLER_JOB_ENV_VARS or not isinstance(value, str)
        for key, value in uv_options.items()
    ):
        raise PluginServiceError("invalid uv job options")

    home = work / "home"
    home.mkdir()
    tmp = work / "tmp"
    tmp.mkdir()
    target = work / "target"
    env = installer_env()
    for key in (*PROXY_ENV_VARS, "NO_PROXY", "no_proxy", "XDG_CACHE_HOME", "PYTHONPATH"):
        env.pop(key, None)
    # Role-level policies take precedence. In particular an offline service
    # cannot be made online by a job request.
    env = {**uv_options, **env, **proxies}
    offline = (uv_options.get("UV_OFFLINE", ""), env.get("UV_OFFLINE", ""))
    if any(value.casefold() in {"true", "1", "yes", "on"} for value in offline):
        env["UV_OFFLINE"] = "true"
    env.update(
        HOME=str(home), TMPDIR=str(tmp),
        UV_CACHE_DIR=os.environ.get("UV_CACHE_DIR") or str(work / "cache"),
    )
    uv = os.environ.get("VEA_UV_BIN") or shutil.which("uv")
    if not uv:
        raise PluginServiceError("uv is unavailable")
    command = [uv, "--no-config", "pip", "install", "--target", str(target),
               "--python", sys.executable, "--link-mode", "copy"]
    if role == "installer":
        command.append("--no-build")
    if request["use_index"] is True:
        if index:
            env["UV_DEFAULT_INDEX"] = index
    elif not from_index:
        command.extend(("--no-index", "--no-deps"))
    else:
        raise PluginServiceError("missing index for index install")

    process = await asyncio.create_subprocess_exec(
        *_supervised(*command, source), env=env, cwd=work, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    completion = asyncio.create_task(process.wait())
    disconnected = asyncio.create_task(reader.read(1))
    try:
        done, _ = await asyncio.wait((completion, disconnected), return_when=asyncio.FIRST_COMPLETED)
        if disconnected in done:
            raise PluginServiceError("installation client disconnected")
        if completion.result():
            raise PluginServiceError("uv could not install the plugin package")
    finally:
        disconnected.cancel()
        completion.cancel()
        await asyncio.gather(disconnected, completion, return_exceptions=True)
        await _stop_process(process)
    await _send_artifact(target, writer)


async def _install_job(
    role: str, request: dict[str, Any], reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    with tempfile.TemporaryDirectory(prefix="vea-plugin-job-") as work:
        await _install(role, request, reader, writer, Path(work))


async def _serve(role: str) -> None:
    root = os.environ["VEA_PLUGIN_SERVICE_SOCKET_DIR"]
    path = socket_path(root, role)
    verify_local_uid(role)
    install_lock = asyncio.Lock()
    tasks: set[asyncio.Task[Any]] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        tasks.add(task)
        verified = False
        try:
            verify_peer(writer.get_extra_info("socket"), "app")
            verified = True
            request = await asyncio.wait_for(read_header(reader), timeout=5)
            if role == "worker":
                if request == {"health": True}:
                    _write_frame(writer, {"healthy": True})
                    await writer.drain()
                    return
                await _worker(request, reader, writer)
            else:
                async with install_lock:
                    await asyncio.wait_for(
                        _install_job(role, request, reader, writer), INSTALL_TIMEOUT_SECONDS
                    )
        except WorkerSessionError:
            if verified:
                with contextlib.suppress(OSError):
                    _write_frame(writer, WORKER_SESSION_UNAVAILABLE)
                    await writer.drain()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, EOFError):
            # Never forward an exception or uv output that might contain a credential.
            if verified and role != "worker":
                with contextlib.suppress(OSError):
                    _write_frame(writer, {"error": "plugin installation service failed"})
                    await writer.drain()
        finally:
            tasks.discard(task)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    if path.exists():
        # A second live instance must not unlink the active listener.
        try:
            _, existing = await asyncio.open_unix_connection(path)
        except ConnectionRefusedError:
            path.unlink()
        else:
            existing.close()
            raise RuntimeError(f"the {role} service is already listening")
    limit = MAX_REQUEST_BYTES + 1 if role == "worker" else HEADER_LIMIT
    server = await asyncio.start_unix_server(handle, path, limit=limit)
    path.chmod(0o660)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        async with server:
            await stop.wait()
    finally:
        for task in tasks.copy():
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("worker", "installer", "builder"))
    args = parser.parse_args()
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix=f"vea-{args.role}-") as home:
        os.environ["HOME"] = home
        os.environ["TMPDIR"] = home
        asyncio.run(_serve(args.role))


if __name__ == "__main__":
    main()
