"""既定で正しく振る舞うコレクタのスタブと、その配布物用のソース。

アプリ側と作者側の両方で「とりあえず正しいコレクタ」が必要になる。毎回書き下ろすと
細部がずれて、テストが何を確かめているのか分からなくなる。
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from typing import Any, Literal

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectionContext,
    CollectorBase,
    CollectorManifest,
    MetricDefinition,
)

__all__ = ["StubCollector", "stub_manifest", "stub_plugin_source"]

#: スタブが使う既定のプラグイン ID。
STUB_PLUGIN_ID = "example.temperature"
#: スタブが使う既定のメトリクスキー。
STUB_METRIC_KEY = "example.host.temperature_c"

Fault = Literal["hang", "crash", "raise"]


def stub_metric_definition(**overrides: Any) -> MetricDefinition:
    """既定のメトリクス定義。"""
    fields: dict[str, Any] = {
        "key": STUB_METRIC_KEY,
        "display_name": "Temperature",
        "unit": "C",
        "entity_type": "HostSystem",
    }
    fields.update(overrides)
    return MetricDefinition(**fields)


def stub_manifest(**overrides: Any) -> CollectorManifest:
    """検証を通る :class:`CollectorManifest` を作る。

    ``data_kinds`` と ``metric_definitions`` が整合した状態で返るので、
    「宣言していないデータを返した」という拒否を踏まない。
    """
    fields: dict[str, Any] = {
        "id": STUB_PLUGIN_ID,
        "display_name": "Example Temperature",
        "version": "0.1.0",
        "data_kinds": frozenset({"metric"}),
        "metric_definitions": (stub_metric_definition(),),
    }
    fields.update(overrides)
    return CollectorManifest(**fields)


class StubCollector(CollectorBase):
    """指定したバッチを返すだけのコレクタ。

    ``collect`` の呼び出し回数と渡された :class:`CollectionContext` を記録するので、
    レジストリやランタイム側のテストで「何が渡ったか」を確認できる。

    Args:
        manifest: 使うマニフェスト。省略時は :func:`stub_manifest`。
        batches: 返すバッチを順に指定する。尽きたら最後のものを返し続ける。
            省略時は、マニフェストのメトリクス定義に沿ったサンプル 1 件と
            ``next_cursor`` を持つバッチを 1 つ返す。
        fault: ``"raise"`` で例外を送出する。``"hang"`` / ``"crash"`` は
            :func:`stub_plugin_source` 側（別プロセス）でのみ意味を持つ。
        error: ``fault="raise"`` のときに送出する例外。
    """

    #: クラス定義の時点で検証されるマニフェスト。インスタンスごとに差し替えられる。
    manifest = stub_manifest()

    def __init__(
        self,
        manifest: CollectorManifest | None = None,
        *,
        batches: Sequence[CollectionBatch] | None = None,
        fault: Fault | None = None,
        error: BaseException | None = None,
    ) -> None:
        if manifest is not None:
            # 基底では ClassVar だが、スタブはインスタンスごとに差し替えたい
            # （1 つのテストで複数のマニフェストを使うため）。
            self.manifest = manifest  # type: ignore[misc]
        self._batches = tuple(batches) if batches is not None else (self._default_batch(),)
        self._fault = fault
        self._error = error
        #: ``start()`` / ``stop()`` / ``collect()`` の呼び出し回数。
        self.start_count = 0
        self.stop_count = 0
        self.collect_count = 0
        #: ``collect()`` に渡された context の記録。
        self.contexts: list[CollectionContext] = []

    def _default_batch(self) -> CollectionBatch:
        definitions = self.manifest.metric_definitions
        if not definitions or "metric" not in self.manifest.data_kinds:
            return CollectionBatch(next_cursor="cursor-1")
        return CollectionBatch(
            metrics=tuple(
                definition.at(
                    entity_moid=f"host-{index}",
                    entity_name=f"esxi-{index}",
                    value=42.5,
                )
                for index, definition in enumerate(definitions, start=1)
            ),
            next_cursor="cursor-1",
        )

    async def start(self) -> None:
        self.start_count += 1

    async def stop(self) -> None:
        self.stop_count += 1

    async def collect(self, context: CollectionContext) -> CollectionBatch:
        self.collect_count += 1
        self.contexts.append(context)
        if self._fault == "raise":
            raise self._error or RuntimeError("stub collector failure")
        index = min(self.collect_count, len(self._batches)) - 1
        return self._batches[index]


def stub_plugin_source(
    *,
    plugin_id: str = STUB_PLUGIN_ID,
    display_name: str = "Example Temperature",
    version: str = "0.1.0",
    metric_key: str = STUB_METRIC_KEY,
    entity_type: str = "HostSystem",
    value: float = 42.5,
    next_cursor: str | None = "cursor-1",
    emit_metric: bool = True,
    noisy_stdout: bool = False,
    fault_env_var: str | None = None,
    raise_message: str = "synthetic collector failure",
) -> str:
    """ディスク上の配布物に書き出すための、単一モジュールのソースを返す。

    プラグインは別プロセスで import されるため、スタブをインスタンスとして渡すことが
    できない。テストは配布物を組み立てる必要があり、そのモジュール本体をここで作る。

    依存は ``vcenter-event-assistant-plugin-api`` だけである。entry point は
    ``<plugin_id> = <module>:build_collector`` の形で書くこと（entry point 名は
    ``manifest.id`` と一致していなければならない）。

    Args:
        emit_metric: ``False`` なら空のバッチを返す。
        noisy_stdout: ``True`` なら ``print`` する。stdout はワーカーの
            JSON Lines プロトコル専用なので、これで汚しても壊れないことを確認できる。
        fault_env_var: 指定すると、その環境変数で障害注入を切り替える
            （``hang`` / ``crash`` / ``raise``）。プロセス分離の確認に使う。
    """
    parts = [
        '"""Stub collector generated by vcenter_event_assistant_plugin_api.testing."""',
        "",
        "import asyncio",
        "import os",
        "",
        "from vcenter_event_assistant_plugin_api import (",
        "    CollectionBatch,",
        "    CollectorManifest,",
        "    MetricDefinition,",
        ")",
        "",
    ]
    if fault_env_var:
        parts += [f"MODE = os.environ.get({fault_env_var!r}, 'ok')", ""]
    parts += [
        "",
        "class Collector:",
        "    manifest = CollectorManifest(",
        f"        {plugin_id!r},",
        f"        {display_name!r},",
        f"        {version!r},",
        "        data_kinds=frozenset({'metric'}),",
        "        metric_definitions=(",
        "            MetricDefinition(",
        f"                {metric_key!r}, 'Temperature', 'C', {entity_type!r}",
        "            ),",
        "        ),",
        "    )",
        "",
        "    async def start(self):",
        "        return None",
        "",
        "    async def stop(self):",
        "        return None",
        "",
        "    async def collect(self, context):",
    ]
    if fault_env_var:
        parts += [
            "        if MODE == 'hang':",
            "            await asyncio.sleep(3600)",
            "        if MODE == 'crash':",
            "            os._exit(9)",
            "        if MODE == 'raise':",
            f"            raise RuntimeError({raise_message!r})",
        ]
    if noisy_stdout:
        parts.append("        print('stdout noise from the plugin')")
    if emit_metric:
        parts += [
            "        return CollectionBatch(",
            "            metrics=(",
            "                self.manifest.metric_definitions[0].at(",
            "                    entity_moid='host-1',",
            "                    entity_name=context.target.name,",
            f"                    value={value!r},",
            "                ),",
            "            ),",
            f"            next_cursor={next_cursor!r},",
            "        )",
        ]
    else:
        parts.append(f"        return CollectionBatch(next_cursor={next_cursor!r})")
    parts += [
        "",
        "",
        "def build_collector():",
        "    return Collector()",
        "",
    ]
    return textwrap.dedent("\n".join(parts))
