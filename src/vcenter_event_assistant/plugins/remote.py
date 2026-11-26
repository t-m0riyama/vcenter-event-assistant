"""Parent-side proxy for collector plugins running in a worker process.

``RemoteCollectorPlugin`` は ``CollectorPlugin`` Protocol を構造的に満たすので、
レジストリ・ランタイム・API から見ると通常のプラグインと同じように扱える。
実際の ``start`` / ``collect`` / ``stop`` は子プロセスへ JSON Lines で委譲する。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
import sys
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from vcenter_event_assistant.plugins.publication import published_paths
from vcenter_event_assistant.plugins.request_files import read_file
from vcenter_event_assistant.plugins.service_protocol import (
    WORKER_SESSION_READY,
    PluginServiceError,
    connect,
    encode_header,
    read_header,
    socket_path,
    verify_peer,
)

from vcenter_event_assistant.plugins.subprocess_env import worker_env
from vcenter_event_assistant_plugin_api import CollectionBatch, CollectorManifest

from vcenter_event_assistant.plugins.wire import (
    ConnectionParams,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    batch_from_json,
    context_to_json,
    manifest_from_json,
)
from vcenter_event_assistant.settings import get_settings

logger = logging.getLogger(__name__)

_WORKER_MODULE = "vcenter_event_assistant.plugins.worker"
_DISCOVER_TIMEOUT_SECONDS = 60.0
_SHUTDOWN_GRACE_SECONDS = 5.0


class CollectorWorkerError(RuntimeError):
    """ワーカーが要求を処理できなかった。

    渡す文言は失敗の記録の型名の位置に残り、画面の案内（frontend/src/utils/collectionErrorMessage.ts）
    の対象になる。文言を足したら tests/test_collection_error_records.py の一覧を書き直す。

    ``str()`` はプラグイン側の例外型名（ワーカーが返した ``error``）であり、
    従来からこの形を保っている。``detail`` はワーカーが allow-list に載る型に
    限って添えてくるメッセージで、無い場合は ``None``。
    """

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class CollectorWorkerServiceError(CollectorWorkerError):
    """The separated worker service could not be contacted."""


def plugin_search_paths(plugin_dir: str | None) -> list[str]:
    """``<plugin_dir>/<distribution>/<version>/`` を列挙する。

    ディレクトリ単位で分離しているため、アンインストールとロールバックは
    そのディレクトリの削除だけで完結する。
    """
    if not plugin_dir:
        return []
    root = Path(plugin_dir)
    if not root.is_dir():
        return []
    paths: list[str] = []
    for distribution in sorted(root.iterdir()):
        if distribution.name.startswith(".") or not distribution.is_dir():
            continue
        for version in sorted(distribution.iterdir()):
            if version.is_dir():
                paths.append(str(version.resolve()))
    return paths


def _worker_command(plugin_paths: list[str]) -> list[str]:
    command = [sys.executable, "-m", _WORKER_MODULE]
    for path in plugin_paths:
        command += ["--plugin-path", path]
    return command


class CollectorWorker:
    """1 プラグインに対応する子プロセスとその JSON Lines チャネル。

    要求は ``_lock`` で直列化する。1 プラグイン 1 ワーカーであり、同一プラグインの
    同時実行は ``runtime`` 側のロックで既に排除されているため、直列で十分である。
    """

    def __init__(self, plugin_paths: list[str], *, label: str) -> None:
        self._plugin_paths = plugin_paths
        self._label = label
        self._process: asyncio.subprocess.Process | None = None
        self._streams: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0

    @property
    def is_running(self) -> bool:
        if self._streams:
            reader, writer = self._streams
            return not reader.at_eof() and not writer.is_closing()
        return self._process is not None and self._process.returncode is None

    async def ensure_started(self) -> None:
        if self.is_running:
            return
        await self.kill()
        settings = get_settings()
        if root := settings.plugin_service_socket_dir:
            try:
                header = encode_header({"paths": self._plugin_paths, "env": worker_env(settings)})
                reader, writer = await connect(root, "worker", limit=MAX_RESPONSE_BYTES + 1)
                self._streams = reader, writer
                async with asyncio.timeout(6):
                    writer.write(header)
                    await writer.drain()
                    if await read_header(reader) != WORKER_SESSION_READY:
                        raise PluginServiceError("worker session unavailable")
            except (OSError, ValueError, PluginServiceError) as exc:
                await self.kill()
                raise CollectorWorkerServiceError("plugin worker service is unavailable") from exc
            except asyncio.CancelledError:
                await self.kill()
                raise
            return
        self._process = await asyncio.create_subprocess_exec(
            *_worker_command(self._plugin_paths),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,
            limit=MAX_RESPONSE_BYTES + 1,
            env=worker_env(settings),
        )
        logger.info(
            "collector worker started label=%s pid=%s", self._label, self._process.pid
        )

    async def request(
        self, payload: dict[str, Any], *, timeout: float, auto_start: bool = True
    ) -> dict[str, Any]:
        """1 要求を送って応答を待つ。タイムアウト時はワーカーを kill する。

        ハングしたプラグインを確実に打ち切れることが、プロセス分離を採用した主目的である。
        """
        async with self._lock:
            if auto_start:
                await self.ensure_started()
            elif not self.is_running:
                raise CollectorWorkerError("worker is not running")
            separated = self._streams is not None
            if self._streams is not None:
                reader, writer = self._streams
            else:
                process = self._process
                assert process is not None and process.stdin and process.stdout
                reader, writer = process.stdout, process.stdin
            self._next_id += 1
            payload = {**payload, "id": self._next_id}
            encoded = (json.dumps(payload) + "\n").encode()
            if self._streams and len(encoded) > MAX_REQUEST_BYTES:
                raise CollectorWorkerError("plugin worker request exceeds size limit")
            try:
                async with asyncio.timeout(timeout):
                    writer.write(encoded)
                    await writer.drain()
                    line = await reader.readline()
            except asyncio.TimeoutError:
                logger.warning(
                    "collector worker timed out label=%s op=%s; killing worker",
                    self._label,
                    payload.get("op"),
                )
                await self.kill()
                if separated and payload.get("op") == "start":
                    await _verify_worker_listener()
                raise
            except ValueError as exc:
                await self.kill()
                raise CollectorWorkerError("worker response exceeds size limit") from exc
            except OSError as exc:
                await self.kill()
                if separated and payload.get("op") == "start":
                    await _verify_worker_listener()
                raise CollectorWorkerError("worker pipe is closed") from exc
            except asyncio.CancelledError:
                await self.kill()
                raise

            if not line:
                await self.kill()
                if separated and payload.get("op") == "start":
                    await _verify_worker_listener()
                raise CollectorWorkerError("worker exited before responding")
            if len(line) > MAX_RESPONSE_BYTES:
                await self.kill()
                raise CollectorWorkerError("worker response exceeds size limit")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                await self.kill()
                raise CollectorWorkerError("worker sent malformed response") from exc
            if not isinstance(response, dict) or (
                self._streams is not None and response.get("id") != self._next_id
            ):
                await self.kill()
                raise CollectorWorkerError("worker sent an invalid response ID")
            if not response.get("ok"):
                detail = response.get("detail")
                raise CollectorWorkerError(
                    str(response.get("error", "unknown error")),
                    detail=str(detail) if detail else None,
                )
            return response.get("result") or {}

    async def kill(self) -> None:
        if self._streams is not None:
            _, writer = self._streams
            self._streams = None
            writer.transport.abort()
        process, self._process = self._process, None
        if process is None or process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
        except asyncio.TimeoutError:  # pragma: no cover - kill 後も残る異常系
            logger.error(
                "collector worker did not exit after kill label=%s", self._label
            )

    async def shutdown(self) -> None:
        """stdin を閉じて自然終了を待ち、猶予を過ぎたら kill する。"""
        if self._streams is not None:
            reader, writer = self._streams
            try:
                writer.write_eof()
                with contextlib.suppress(OSError, TimeoutError):
                    await asyncio.wait_for(reader.read(1), _SHUTDOWN_GRACE_SECONDS)
            finally:
                await self.kill()
            return
        process = self._process
        if process is None or process.returncode is not None:
            self._process = None
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            await asyncio.wait_for(process.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
            self._process = None
        except (asyncio.TimeoutError, BrokenPipeError, ConnectionResetError):
            await self.kill()


class RemoteCollectorPlugin:
    """``CollectorPlugin`` を満たす、ワーカープロセスへの委譲プロキシ。"""

    def __init__(
        self,
        manifest: CollectorManifest,
        *,
        entry_point: str,
        worker: CollectorWorker,
        start_timeout_seconds: float = 60.0,
    ) -> None:
        self.manifest = manifest
        self.entry_point = entry_point
        self._worker = worker
        self._start_timeout_seconds = start_timeout_seconds

    @property
    def installed_paths(self) -> tuple[str, ...]:
        return tuple(self._worker._plugin_paths)

    @property
    def is_running(self) -> bool:
        return self._worker.is_running

    async def start(self) -> None:
        try:
            await self._worker.request(
                {"op": "start", "entry_point": self.entry_point},
                timeout=self._start_timeout_seconds,
            )
        except (CollectorWorkerError, TimeoutError):
            await self._worker.kill()
            raise

    async def collect(self, context) -> CollectionBatch:
        """インプロセス用の署名。リモートでは接続情報を別途渡す必要がある。

        ``runtime.run_collector_for_vcenter`` は ``RemoteCollectorPlugin`` を検出して
        ``collect_with_connection`` を呼ぶ。ここに到達するのは実装漏れである。
        """
        raise CollectorWorkerError(
            "remote collectors require collect_with_connection()"
        )

    async def collect_with_connection(
        self, context, params: ConnectionParams, *, timeout: float,
        worker_files: dict[str, str] | None = None,
    ) -> CollectionBatch:
        result = await self._worker.request(
            {
                "op": "collect",
                "entry_point": self.entry_point,
                **await _request_context(context, params, worker_files),
            },
            timeout=timeout,
        )
        return batch_from_json(result["batch"])

    async def setup_with_connection(
        self, context, params, action, *, timeout, worker_files: dict[str, str] | None = None,
    ):
        result = await self._worker.request(
            {
                "op": "setup",
                "entry_point": self.entry_point,
                **await _request_context(context, params, worker_files),
                "action": action,
            },
            timeout=timeout,
        )
        return result["setup"]

    async def stop(self) -> None:
        try:
            await self._worker.request(
                {"op": "stop", "entry_point": self.entry_point},
                timeout=_SHUTDOWN_GRACE_SECONDS,
            )
        except (asyncio.TimeoutError, CollectorWorkerError):
            # 停止要求が通らないワーカーは、この後の shutdown で kill される。
            logger.warning(
                "collector plugin stop request failed plugin_id=%s", self.manifest.id
            )
        await self._worker.shutdown()


async def _request_context(context, params: ConnectionParams, worker_files: dict[str, str] | None):
    payload = {"context": context_to_json(context), "connection": params.to_json()}
    if get_settings().plugin_service_socket_dir:
        files = dict(worker_files or {})
        if params.verify_ssl and params.ca_bundle_path:
            files[params.ca_bundle_path] = await asyncio.to_thread(read_file, params.ca_bundle_path)
        if files:
            payload["files"] = files
    return payload


async def _verify_worker_listener() -> None:
    """Distinguish a child failure from loss of the authenticated listener."""
    root = get_settings().plugin_service_socket_dir
    if root is None:
        return
    try:
        async with asyncio.timeout(5):
            reader, writer = await connect(root, "worker")
            try:
                writer.write(encode_header({"health": True}))
                await writer.drain()
                if await read_header(reader) != {"healthy": True}:
                    raise PluginServiceError("invalid worker health response")
            finally:
                writer.close()
    except (PluginServiceError, OSError, ValueError) as exc:
        raise CollectorWorkerServiceError("plugin worker service is unavailable") from exc
    writer.close()


def discover_remote_collectors(plugin_dir: str | None) -> list[dict[str, Any]]:
    """インストール済みディレクトリ全体から entry point と manifest を列挙する。"""
    return discover_collectors_at(_active_paths(plugin_dir))


def _active_paths(plugin_dir: str | None) -> list[str]:
    if get_settings().plugin_service_socket_dir and plugin_dir:
        return published_paths(Path(plugin_dir).resolve())
    return plugin_search_paths(plugin_dir)


def _discovery_lines(connection: socket.socket, deadline: float) -> Iterator[bytes]:
    remaining_bytes = MAX_RESPONSE_BYTES + len(encode_header(WORKER_SESSION_READY))
    line = bytearray()
    while remaining_bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("plugin discovery timed out")
        connection.settimeout(remaining)
        chunk = connection.recv(min(65536, remaining_bytes))
        if not chunk:
            return
        remaining_bytes -= len(chunk)
        parts = chunk.split(b"\n")
        for part in parts[:-1]:
            line.extend(part)
            yield bytes(line)
            line.clear()
        line.extend(parts[-1])


def _discover_via_service(root: str, paths: list[str], request: str) -> str:
    deadline = time.monotonic() + _DISCOVER_TIMEOUT_SECONDS
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(_DISCOVER_TIMEOUT_SECONDS)
            connection.connect(str(socket_path(root, "worker")))
            verify_peer(connection, "worker")
            connection.settimeout(max(0.0, deadline - time.monotonic()))
            connection.sendall(
                encode_header({"paths": paths, "env": worker_env(get_settings())})
                + request.encode()
            )
            lines = _discovery_lines(connection, deadline)
            if next(lines, None) != encode_header(WORKER_SESSION_READY).rstrip(b"\n"):
                raise CollectorWorkerServiceError("plugin discovery session unavailable")
            for line in lines:
                try:
                    response = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(response, dict) and response.get("id") == 1 and type(response.get("ok")) is bool:
                    return line.decode()
            raise CollectorWorkerError("plugin discovery did not return a complete response")
    except (OSError, ValueError, PluginServiceError) as exc:
        raise CollectorWorkerError("plugin worker discovery service is unavailable") from exc


def _log_discovery_output(stderr: str, level: int) -> None:
    """検出ワーカーの stderr を親のログへ転記する。

    ``discover_collectors_at`` は ``capture_output=True`` でワーカーを起こすため、
    そのままでは entry point 読み込み失敗のトレースバックが捨てられてしまう。
    """
    text = (stderr or "").strip()
    if not text:
        return
    logger.log(level, "collector plugin discovery worker output:\n%s", text)


def discover_collectors_at(
    paths: list[str], *, include_environment: bool = False
) -> list[dict[str, Any]]:
    """短命のワーカーで、指定パスの entry point と manifest を列挙する（同期）。

    親プロセスでプラグインを import すると分離が崩れるため、検出もワーカー経由で行う。
    ``build_collector_registry`` が同期であることに合わせ、ここも ``subprocess.run`` を使う。
    インストール直後の検証では、新しい配布物のパスだけを渡して単独で検証する。

    Returns:
        ``{"name": ..., "manifest": {...}}`` または ``{"name": ..., "error": ...}`` の一覧。
    """
    import subprocess

    request = (
        json.dumps(
            {
                "id": 1,
                "op": "discover",
                **({} if include_environment else {"paths": paths}),
            }
        )
        + "\n"
    )
    settings = get_settings()
    if root := settings.plugin_service_socket_dir:
        stdout = _discover_via_service(root, paths, request)
        stderr, returncode = "", None
    else:
        try:
            completed = subprocess.run(
                _worker_command(paths),
                input=request,
                capture_output=True,
                check=False,
                text=True,
                timeout=_DISCOVER_TIMEOUT_SECONDS,
                env=worker_env(settings),
            )
        except subprocess.TimeoutExpired:
            logger.error("collector plugin discovery timed out")
            raise CollectorWorkerError("plugin discovery timed out") from None
        stdout, stderr, returncode = completed.stdout, completed.stderr, completed.returncode

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(response, dict) or "ok" not in response:
            continue
        if not response.get("ok"):
            _log_discovery_output(stderr, logging.WARNING)
            raise CollectorWorkerError(
                str(response.get("error", "discovery failed")),
                detail=str(response["detail"]) if response.get("detail") else None,
            )
        plugins = list(response.get("result", {}).get("plugins", []))
        # 検出ワーカーは capture_output で起動するため、その stderr は親に継承されない。
        # 読み込みに失敗した entry point のトレースバックはそこにしかないので、
        # 失敗があったときだけ親のログへ転記する。
        failed = any("manifest" not in item for item in plugins)
        _log_discovery_output(
            stderr, logging.WARNING if failed else logging.DEBUG
        )
        return plugins

    logger.error(
        "collector plugin discovery produced no response rc=%s", returncode
    )
    raise CollectorWorkerError("plugin discovery produced no response")


def build_remote_plugins(
    plugin_dir: str | None,
    *,
    include_environment: bool = True,
) -> tuple[list[RemoteCollectorPlugin], dict[str, str]]:
    """検出結果からプロキシ群を組み立てる。

    Returns:
        ``(プロキシ一覧, entry point 名 → 失敗理由)``。
    """
    paths = _active_paths(plugin_dir)
    discovered = discover_collectors_at(paths, include_environment=include_environment)
    names = Counter(str(item.get("name", "")) for item in discovered)
    plugins: list[RemoteCollectorPlugin] = []
    failures: dict[str, str] = {}
    for item in discovered:
        name = str(item.get("name", ""))
        if names[name] > 1:
            failures[name] = "duplicate collector entry point"
            continue
        if "manifest" not in item:
            # detail はワーカーが allow-list（import 名など機密を含みえない型）に
            # 限って付けてくる。付いていれば失敗理由として表に出す。
            detail = item.get("detail")
            reason = f"{item.get('error', 'unknown')}"
            if detail:
                reason = f"{reason}: {detail}"
            failures[name] = f"load failed: {reason}"
            continue
        try:
            manifest = manifest_from_json(item["manifest"])
        except Exception as exc:
            failures[name] = f"invalid manifest: {type(exc).__name__}"
            continue
        plugins.append(
            RemoteCollectorPlugin(
                manifest,
                entry_point=name,
                worker=CollectorWorker(paths, label=name),
            )
        )
    return plugins, failures
