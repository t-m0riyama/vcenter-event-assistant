"""Parent-side proxy for collector plugins running in a worker process.

``RemoteCollectorPlugin`` は ``CollectorPlugin`` Protocol を構造的に満たすので、
レジストリ・ランタイム・API から見ると通常のプラグインと同じように扱える。
実際の ``start`` / ``collect`` / ``stop`` は子プロセスへ JSON Lines で委譲する。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from vcenter_event_assistant_plugin_api import CollectionBatch, CollectorManifest

from vcenter_event_assistant.plugins.wire import (
    ConnectionParams,
    batch_from_json,
    context_to_json,
    manifest_from_json,
)

logger = logging.getLogger(__name__)

_WORKER_MODULE = "vcenter_event_assistant.plugins.worker"
_DISCOVER_TIMEOUT_SECONDS = 60.0
_SHUTDOWN_GRACE_SECONDS = 5.0


class CollectorWorkerError(RuntimeError):
    """ワーカーが要求を処理できなかった。"""


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
        if not distribution.is_dir():
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
        self._lock = asyncio.Lock()
        self._next_id = 0

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def ensure_started(self) -> None:
        if self.is_running:
            return
        self._process = await asyncio.create_subprocess_exec(
            *_worker_command(self._plugin_paths),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,
        )
        logger.info(
            "collector worker started label=%s pid=%s", self._label, self._process.pid
        )

    async def request(
        self, payload: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        """1 要求を送って応答を待つ。タイムアウト時はワーカーを kill する。

        ハングしたプラグインを確実に打ち切れることが、プロセス分離を採用した主目的である。
        """
        async with self._lock:
            await self.ensure_started()
            process = self._process
            assert process is not None and process.stdin and process.stdout
            self._next_id += 1
            payload = {**payload, "id": self._next_id}
            try:
                process.stdin.write((json.dumps(payload) + "\n").encode())
                await process.stdin.drain()
                line = await asyncio.wait_for(
                    process.stdout.readline(), timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "collector worker timed out label=%s op=%s; killing worker",
                    self._label,
                    payload.get("op"),
                )
                await self.kill()
                raise
            except (BrokenPipeError, ConnectionResetError) as exc:
                await self.kill()
                raise CollectorWorkerError("worker pipe is closed") from exc

            if not line:
                await self.kill()
                raise CollectorWorkerError("worker exited before responding")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                await self.kill()
                raise CollectorWorkerError("worker sent malformed response") from exc
            if not response.get("ok"):
                raise CollectorWorkerError(str(response.get("error", "unknown error")))
            return response.get("result") or {}

    async def kill(self) -> None:
        process, self._process = self._process, None
        if process is None or process.returncode is not None:
            return
        process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
        except asyncio.TimeoutError:  # pragma: no cover - kill 後も残る異常系
            logger.error("collector worker did not exit after kill label=%s", self._label)

    async def shutdown(self) -> None:
        """stdin を閉じて自然終了を待ち、猶予を過ぎたら kill する。"""
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

    async def start(self) -> None:
        await self._worker.request(
            {"op": "start", "entry_point": self.entry_point},
            timeout=self._start_timeout_seconds,
        )

    async def collect(self, context) -> CollectionBatch:
        """インプロセス用の署名。リモートでは接続情報を別途渡す必要がある。

        ``runtime.run_collector_for_vcenter`` は ``RemoteCollectorPlugin`` を検出して
        ``collect_with_connection`` を呼ぶ。ここに到達するのは実装漏れである。
        """
        raise CollectorWorkerError(
            "remote collectors require collect_with_connection()"
        )

    async def collect_with_connection(
        self, context, params: ConnectionParams, *, timeout: float
    ) -> CollectionBatch:
        result = await self._worker.request(
            {
                "op": "collect",
                "entry_point": self.entry_point,
                "context": context_to_json(context),
                "connection": params.to_json(),
            },
            timeout=timeout,
        )
        return batch_from_json(result["batch"])

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


def discover_remote_collectors(plugin_dir: str | None) -> list[dict[str, Any]]:
    """インストール済みディレクトリ全体から entry point と manifest を列挙する。"""
    return discover_collectors_at(plugin_search_paths(plugin_dir))


def discover_collectors_at(paths: list[str]) -> list[dict[str, Any]]:
    """短命のワーカーで、指定パスの entry point と manifest を列挙する（同期）。

    親プロセスでプラグインを import すると分離が崩れるため、検出もワーカー経由で行う。
    ``build_collector_registry`` が同期であることに合わせ、ここも ``subprocess.run`` を使う。
    インストール直後の検証では、新しい配布物のパスだけを渡して単独で検証する。

    Returns:
        ``{"name": ..., "manifest": {...}}`` または ``{"name": ..., "error": ...}`` の一覧。
    """
    import subprocess

    request = json.dumps({"id": 1, "op": "discover"}) + "\n"
    try:
        completed = subprocess.run(
            _worker_command(paths),
            input=request,
            capture_output=True,
            text=True,
            timeout=_DISCOVER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        logger.error("collector plugin discovery timed out")
        raise CollectorWorkerError("plugin discovery timed out") from None

    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not response.get("ok"):
            raise CollectorWorkerError(str(response.get("error", "discovery failed")))
        return list(response.get("result", {}).get("plugins", []))

    logger.error(
        "collector plugin discovery produced no response rc=%s", completed.returncode
    )
    raise CollectorWorkerError("plugin discovery produced no response")


def build_remote_plugins(
    plugin_dir: str | None,
) -> tuple[list[RemoteCollectorPlugin], dict[str, str]]:
    """検出結果からプロキシ群を組み立てる。

    Returns:
        ``(プロキシ一覧, entry point 名 → 失敗理由)``。
    """
    discovered = discover_remote_collectors(plugin_dir)
    paths = plugin_search_paths(plugin_dir)
    plugins: list[RemoteCollectorPlugin] = []
    failures: dict[str, str] = {}
    for item in discovered:
        name = str(item.get("name", ""))
        if "manifest" not in item:
            failures[name] = f"load failed: {item.get('error', 'unknown')}"
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
