"""Out-of-process host for external collector plugins.

``python -m vcenter_event_assistant.plugins.worker`` で起動し、stdin から JSON Lines の
要求を読み、stdout へ JSON Lines の応答を書く。stdout はプロトコル専用であり、
プラグインが ``print`` した出力が混ざらないよう、起動直後に ``sys.stdout`` を差し替える。

このモジュールは本アプリのコードであってプラグインではない。vCenter への接続は
ここで確立し、プラグインへは ``open_vcenter_connection`` ファクトリだけを渡すため、
``packages/plugin-api`` の公開契約は変更せずに済む。

セキュリティ上の注意: 同一ワーカー内のプラグインは、渡された接続情報へ到達しうる。
プロセス分離が提供するのはクラッシュ・ハング・依存衝突からの隔離であり、
悪意あるコードに対する完全なサンドボックスではない。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from importlib.metadata import entry_points
from typing import Any

ENTRY_POINT_GROUP = "vcenter_event_assistant.collectors"


def _extend_sys_path(plugin_paths: list[str]) -> None:
    """インストール済みプラグインのディレクトリを import 経路へ追加する。

    アプリ本体の依存を優先させたいので末尾に足す（先頭に足すとプラグインが同梱する
    古い依存でアプリ側のライブラリを上書きしてしまう）。
    """
    for path in plugin_paths:
        if path and path not in sys.path:
            sys.path.append(path)


def _discover() -> list[dict[str, Any]]:
    """entry point を列挙し、manifest だけを返す（プラグイン実体は親へ渡さない）。"""
    from vcenter_event_assistant.plugins.wire import manifest_to_json

    found: list[dict[str, Any]] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            plugin = ep.load()()
            found.append(
                {"name": ep.name, "manifest": manifest_to_json(plugin.manifest)}
            )
        except Exception as exc:
            found.append({"name": ep.name, "error": type(exc).__name__})
    return found


class _PluginHost:
    """1 ワーカーが受け持つプラグイン実体のキャッシュ。"""

    def __init__(self) -> None:
        self._plugins: dict[str, Any] = {}

    def load(self, entry_point_name: str):
        plugin = self._plugins.get(entry_point_name)
        if plugin is not None:
            return plugin
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            if ep.name == entry_point_name:
                plugin = ep.load()()
                self._plugins[entry_point_name] = plugin
                return plugin
        raise LookupError(f"entry point not found: {entry_point_name}")

    def loaded(self) -> list[Any]:
        return list(self._plugins.values())


@asynccontextmanager
async def _open_connection(params):
    from vcenter_event_assistant.collectors.connection import (
        connect_vcenter,
        disconnect,
    )

    si = await asyncio.to_thread(
        connect_vcenter,
        host=params.host,
        protocol=params.protocol,
        port=params.port,
        username=params.username,
        password=params.password,
        proxy_url=params.proxy_url,
        verify_ssl=params.verify_ssl,
        ca_bundle_path=params.ca_bundle_path,
    )
    try:
        yield si
    finally:
        await asyncio.to_thread(disconnect, si)


async def _handle(host: _PluginHost, request: dict[str, Any]) -> Any:
    from vcenter_event_assistant_plugin_api import CollectionContext

    from vcenter_event_assistant.plugins.wire import (
        ConnectionParams,
        batch_to_json,
        target_from_json,
    )

    op = request.get("op")
    if op == "ping":
        return {"ok": True}
    if op == "discover":
        return {"plugins": _discover()}

    entry_point_name = str(request["entry_point"])
    plugin = host.load(entry_point_name)

    if op == "start":
        await plugin.start()
        return {}
    if op == "stop":
        await plugin.stop()
        return {}
    if op == "collect":
        raw_context = request["context"]
        params = ConnectionParams.from_json(request["connection"])
        context = CollectionContext(
            target=target_from_json(raw_context["target"]),
            config=dict(raw_context.get("config", {})),
            previous_cursor=raw_context.get("previous_cursor"),
            open_vcenter_connection=lambda: _open_connection(params),
            mock_mode=bool(raw_context.get("mock_mode", False)),
        )
        batch = await plugin.collect(context)
        return {"batch": batch_to_json(batch)}

    raise ValueError(f"unknown op: {op}")


async def _serve(plugin_paths: list[str]) -> int:
    _extend_sys_path(plugin_paths)

    # プラグインの print / 依存ライブラリのバナー出力がプロトコルを壊さないよう、
    # stdout を退避して以後の sys.stdout は stderr に向ける。
    protocol_out = sys.stdout
    sys.stdout = sys.stderr

    from vcenter_event_assistant.settings import get_settings
    from vcenter_event_assistant.settings_binding import bind_settings

    # connect_vcenter は require_settings() を参照するため、束縛しておく。
    bind_settings(get_settings())

    host = _PluginHost()
    loop = asyncio.get_running_loop()

    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        request_id = request.get("id")
        try:
            result = await _handle(host, request)
            response = {"id": request_id, "ok": True, "result": result}
        except Exception as exc:
            # 詳細な例外文言は認証情報やレスポンス本文を含みうるため型名のみ返す。
            print(
                f"collector worker request failed op={request.get('op')!r}: {exc!r}",
                file=sys.stderr,
            )
            response = {"id": request_id, "ok": False, "error": type(exc).__name__}
        protocol_out.write(json.dumps(response) + "\n")
        protocol_out.flush()

    for plugin in host.loaded():
        try:
            await plugin.stop()
        except Exception:  # pragma: no cover - 終了処理のベストエフォート
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vcenter-event-assistant-collector-worker")
    parser.add_argument(
        "--plugin-path",
        action="append",
        default=[],
        help="Directory to append to sys.path (repeatable).",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_serve(args.plugin_path))


if __name__ == "__main__":  # pragma: no cover - プロセスエントリ
    raise SystemExit(main())
