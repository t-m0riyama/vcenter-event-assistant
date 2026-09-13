"""Generate a new collector plugin project.

```bash
python -m vcenter_event_assistant_plugin_api.scaffold my-sensor-collector --kind metric
cd my-sensor-collector
uv sync && uv run pytest -q
```

生成物は**最初から通る状態**である。宣言的な基底クラス、``config`` 経由の設定読み、
``vmware`` ヘルパ、``get_plugin_logger`` でのログ、そして ``testing.run_collect`` を
使うテストが揃っている。作者が埋めるのは ``sample()`` / ``fetch()`` の中身だけである。

生成する理由は書く量の削減だけではない。``manifest.id`` は **entry point 名・
manifest・メトリクスキーの 3 箇所**に現れ、不一致はレジストリ検証で
``configured plugin is not installed`` のような遠い文言になって初めて露見する。
生成すれば一致が保証される。

cookiecutter や copier は使わない。外部の作者に追加のツール導入を求めるのは、
このパッケージを「依存ゼロで pip install 1 つ」に保つ方針と噛み合わない。
テンプレートは :mod:`string` の ``Template`` だけで展開する。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from string import Template
from typing import Literal

from vcenter_event_assistant_plugin_api import __version__
from vcenter_event_assistant_plugin_api.validation import PLUGIN_ID_PATTERN

__all__ = ["PLUGIN_API_REQUIREMENT", "ScaffoldError", "main", "render", "write_project"]

#: 生成物が宣言する plugin-api の下限（現在の minor）。
_MINOR_VERSION = ".".join(__version__.split(".")[:2])
#: 生成物が宣言する plugin-api の範囲。契約は major で切れるので上限は ``<2``。
PLUGIN_API_REQUIREMENT = (
    f"vcenter-event-assistant-plugin-api>={_MINOR_VERSION},<2"
)

_DISTRIBUTION_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$")

Kind = Literal["metric", "event"]


class ScaffoldError(Exception):
    """入力が不正、または出力先が使えない。"""


def normalize_distribution(name: str) -> str:
    """配布名を正規化する（小文字、区切りはハイフン）。"""
    normalized = re.sub(r"[\s_]+", "-", name.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    if not _DISTRIBUTION_PATTERN.fullmatch(normalized):
        raise ScaffoldError(
            f"invalid distribution name: {name!r}; "
            "use lowercase letters, digits, '-', '.' and '_' (e.g. my-sensor-collector)"
        )
    return normalized


def package_name(distribution: str) -> str:
    """import 可能なパッケージ名。配布名のハイフンとドットをアンダースコアにする。"""
    return re.sub(r"[-.]", "_", distribution)


def class_name(distribution: str) -> str:
    """CamelCase のクラス名。"""
    parts = [part for part in re.split(r"[-._]+", distribution) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Collector"


def default_plugin_id(distribution: str) -> str:
    """既定のプラグイン ID。配布名がそのまま使えることが多い。"""
    return distribution


def _check_plugin_id(plugin_id: str) -> str:
    if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
        raise ScaffoldError(
            f"invalid plugin id: {plugin_id!r}; "
            "it must match ^[a-z0-9][a-z0-9._-]{0,63}$ (the application rejects others)"
        )
    if plugin_id.startswith("builtin."):
        raise ScaffoldError(
            "the 'builtin.' prefix is reserved for the application's own collectors"
        )
    return plugin_id


_PYPROJECT = Template('''\
[project]
name = "$distribution"
version = "0.1.0"
description = "$display_name collector plugin for vCenter Event Assistant"
requires-python = ">=3.12"
dependencies = [
    "$requirement",
]

# entry point 名は manifest.id と**一致していなければならない**。
# ずれるとレジストリが "configured plugin is not installed" として failed にする。
[project.entry-points."vcenter_event_assistant.collectors"]
"$plugin_id" = "$package:build_collector"

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    # `vmware` ヘルパをアプリの外で動かすために pyVmomi が要る。アプリのコレクタ
    # ワーカー内では既に入っているので、上の `dependencies` に足す必要はない。
    "$requirement_vmware",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[build-system]
requires = ["uv_build>=0.10.4,<0.11.0"]
build-backend = "uv_build"
''')

_GITIGNORE = """\
__pycache__/
*.py[cod]
.venv/
dist/
.pytest_cache/
.ruff_cache/
uv.lock
"""

_METRIC_MODULE = Template('''\
"""$display_name collector plugin."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from vcenter_event_assistant_plugin_api import (
    CollectionContext,
    MetricCollector,
    MetricDefinition,
    MetricSampleInput,
    config,
    get_plugin_logger,
    vmware,
)

#: entry point 名（pyproject.toml）と一致させること。
PLUGIN_ID = "$plugin_id"

#: 出すメトリクスの宣言。`at()` がここから metric_key・entity_type・
#: timezone-aware なタイムスタンプを補うので、キーを二度書く必要はない。
#: manifest で宣言していないキーを返すと、バッチが**丸ごと**拒否される。
$metric_constant = MetricDefinition(
    key="$metric_key",
    display_name="$display_name",
    unit="C",
    entity_type="HostSystem",
    category="other",
    description="TODO: describe what this metric measures.",
)

logger = get_plugin_logger(PLUGIN_ID)


class $class_name(MetricCollector):
    """ホストごとに 1 点のメトリクスを返すコレクタ。"""

    id = PLUGIN_ID
    display_name = "$display_name"
    #: 管理画面の詳細行に出る。運用者が有効/無効を判断できる粒度で書く。
    description = "TODO: describe what this collector gathers."
    version = "0.1.0"
    metrics = ($metric_constant,)
    default_interval_seconds = 300

    def sample(
        self, si: Any, context: CollectionContext
    ) -> Iterator[MetricSampleInput]:
        """接続済みの vCenter から 1 回分のサンプルを返す。**同期でよい。**

        実装するのはこのメソッドだけである。接続の開閉、スレッドへの退避、
        `mock_mode` の分岐、`CollectionBatch` の組み立ては基底が行う。
        """
        # 設定は TOML・環境変数・管理画面から与えられる。経路によって型が違う
        # （環境変数由来は常に str）ので、必ず config ヘルパ経由で読む。
        # 機密はこのプラグインが所有する環境変数から読むこと。
        sensor = config.get_str(context.config, "sensor", "default")

        # `iter_hosts` が ContainerView の生成と Destroy() を引き受け、
        # 切断中のホストも除く。
        hosts = vmware.iter_hosts(si)
        logger.info("sampling %d host(s) sensor=%s", len(hosts), sensor)
        for host in hosts:
            entity_moid = vmware.moid(host)
            yield $metric_constant.at(
                entity_moid=entity_moid,
                entity_name=host.name,
                # TODO: ここで実際の値を読む。今は決定的なダミー値である。
                value=_placeholder_value(entity_moid, sensor),
            )


def _placeholder_value(entity_moid: str, sensor: str) -> float:
    """TODO: 実際の測定値に置き換える。"""
    seed = sum(ord(character) for character in f"{entity_moid}:{sensor}")
    return round(seed % 100 + (seed % 10) / 10.0, 2)


#: entry point から呼ばれる引数なしファクトリ。クラス自体がそのまま使える。
build_collector = $class_name
''')

_EVENT_MODULE = Template('''\
"""$display_name collector plugin."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from vcenter_event_assistant_plugin_api import (
    CollectionContext,
    EventCollector,
    EventInput,
    TimestampCursor,
    config,
    get_plugin_logger,
    timeutils,
)

#: entry point 名（pyproject.toml）と一致させること。
PLUGIN_ID = "$plugin_id"

#: 1 回の収集で読むページ数の上限。
MAX_PAGES = 20

logger = get_plugin_logger(PLUGIN_ID)


class $class_name(EventCollector):
    """vCenter のイベントを取り込むコレクタ。"""

    id = PLUGIN_ID
    display_name = "$display_name"
    #: 管理画面の詳細行に出る。運用者が有効/無効を判断できる粒度で書く。
    description = "TODO: describe what this collector gathers."
    version = "0.1.0"
    default_interval_seconds = 120

    #: カーソルは基底が管理する。範囲の開始を 1 秒だけ戻して境界のイベントを
    #: 取りこぼさない（再読分は vmware_key の重複排除で落ちる）。空のバッチでも
    #: 必ず前進するので、同じ範囲を読み続けることはない。
    cursor = TimestampCursor()

    def fetch(
        self, si: Any, context: CollectionContext, *, since: datetime | None
    ) -> Iterator[EventInput]:
        """`since` 以降のイベントを返す。**同期でよい。**

        実装するのはこのメソッドだけである。`since` が None なら初回（またはカーソルが
        読めなかった）なので、取得側の既定の範囲を使う。
        """
        from pyVmomi import vim

        event_types = config.get_str_list(context.config, "event_types", ())

        spec = vim.event.EventFilterSpec()
        spec.time = vim.event.EventFilterSpec.ByTime()
        spec.time.endTime = timeutils.now_utc()
        if since is not None:
            spec.time.beginTime = timeutils.ensure_aware(since)
        if event_types:
            spec.eventTypeId = list(event_types)

        collector = si.RetrieveContent().eventManager.CreateCollectorForEvents(spec)
        try:
            count = 0
            for _ in range(MAX_PAGES):
                page = collector.ReadNextEvents(500)
                if not page:
                    break
                for event in page:
                    converted = self._convert(event)
                    if converted is not None:
                        count += 1
                        yield converted
            else:
                logger.warning("hit MAX_PAGES=%s; more events may remain", MAX_PAGES)
            logger.info("fetched %d event(s) since=%s", count, since)
        finally:
            # 呼ばないとコレクタが vCenter 側に残り続ける。
            collector.DestroyCollector()

    def _convert(self, event: Any) -> EventInput | None:
        """pyVmomi のイベントを `EventInput` にする。

        `vmware_key` は vCenter が振る**自然キー**を使う。重複排除は
        `(vcenter_id, collector_id, vmware_key)` の ON CONFLICT DO NOTHING なので、
        ハッシュで作ると衝突したイベントがエラーもログもなく捨てられる。
        """
        key = getattr(event, "key", None)
        if key is None:
            # key の無いイベントは 0 に潰さずスキップする（潰すと 1 件しか残らない）。
            return None
        entity = getattr(event, "entity", None)
        severity = getattr(event, "severity", None)
        return EventInput(
            # naive な datetime はバッチ全体の拒否になる。
            occurred_at=timeutils.ensure_aware(event.createdTime),
            event_type=type(event).__name__,
            message=getattr(event, "fullFormattedMessage", None) or str(event),
            vmware_key=int(key),
            severity=str(severity).lower() if severity is not None else None,
            user_name=getattr(event, "userName", None),
            entity_name=getattr(entity, "name", None) if entity is not None else None,
            entity_type=type(entity).__name__ if entity is not None else None,
            chain_id=int(event.chainId) if getattr(event, "chainId", None) else None,
        )


#: entry point から呼ばれる引数なしファクトリ。クラス自体がそのまま使える。
build_collector = $class_name
''')

_METRIC_TEST = Template('''\
"""Unit tests for $distribution.

アプリも vCenter も起動せずに `pytest` だけで通る。
"""

from __future__ import annotations

from vcenter_event_assistant_plugin_api.testing import (
    FakeServiceInstance,
    assert_manifest_valid,
    fake_host,
    failing_connection,
    run_collect,
)

from $package import PLUGIN_ID, $class_name


def test_the_manifest_matches_the_entry_point_name() -> None:
    """entry point 名と manifest.id がずれると、アプリは failed として扱う。"""
    assert $class_name.manifest.id == PLUGIN_ID
    assert_manifest_valid($class_name.manifest)


async def test_it_samples_only_connected_hosts() -> None:
    si = FakeServiceInstance(
        hosts=[
            fake_host("host-1", "esxi-a"),
            fake_host("host-2", "esxi-b", connected=False),
        ]
    )
    batch = await run_collect($class_name(), connection=si)

    assert [sample.entity_moid for sample in batch.metrics] == ["host-1"]
    assert batch.metrics[0].metric_key == "$metric_key"
    # `at()` が timezone-aware な時刻を入れる（naive はバッチ全体の拒否になる）。
    assert batch.metrics[0].sampled_at.tzinfo is not None


async def test_mock_mode_never_opens_a_connection() -> None:
    """MOCK_MODE=true のとき接続を開くと、このテストが落ちる。"""
    batch = await run_collect(
        $class_name(),
        mock_mode=True,
        connection=failing_connection(AssertionError("must not connect")),
    )
    assert batch.metrics
''')

_EVENT_TEST = Template('''\
"""Unit tests for $distribution.

アプリも vCenter も起動せずに `pytest` だけで通る。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vcenter_event_assistant_plugin_api.testing import (
    FakeServiceInstance,
    assert_manifest_valid,
    fake_event,
    run_collect,
)

from $package import PLUGIN_ID, $class_name


def test_the_manifest_matches_the_entry_point_name() -> None:
    """entry point 名と manifest.id がずれると、アプリは failed として扱う。"""
    assert $class_name.manifest.id == PLUGIN_ID
    assert_manifest_valid($class_name.manifest)


async def test_it_converts_events_and_advances_the_cursor() -> None:
    now = datetime.now(timezone.utc)
    si = FakeServiceInstance(
        events=[
            fake_event(101, event_type="VmPoweredOnEvent", created_time=now - timedelta(minutes=2)),
            fake_event(102, event_type="VmPoweredOffEvent", created_time=now - timedelta(minutes=1)),
        ]
    )
    batch = await run_collect($class_name(), connection=si)

    # vmware_key は vCenter の自然キーをそのまま使う（ハッシュにすると静かに消える）。
    assert [event.vmware_key for event in batch.events] == [101, 102]
    assert batch.events[0].occurred_at.tzinfo is not None
    # カーソルは最新イベントの時刻まで進む。
    assert batch.next_cursor == (now - timedelta(minutes=1)).isoformat()


async def test_the_cursor_advances_even_on_an_empty_batch() -> None:
    """前進しないと、同じ範囲を永久に読み直す。"""
    batch = await run_collect($class_name(), connection=FakeServiceInstance())

    assert batch.events == ()
    assert batch.next_cursor is not None


async def test_the_window_start_steps_back_by_the_overlap() -> None:
    """境界上のイベントを取りこぼさないため、範囲の開始は 1 秒戻る。"""
    previous = datetime.now(timezone.utc) - timedelta(minutes=10)
    si = FakeServiceInstance()
    await run_collect($class_name(), connection=si, previous_cursor=previous.isoformat())

    assert si.event_filters[0].time.beginTime == previous - timedelta(seconds=1)
''')

_README = Template('''\
# $distribution

vCenter Event Assistant のコレクタプラグイン。

## 開発

```bash
uv sync
uv run pytest -q
```

アプリも vCenter も起動せずにテストが通る。`tests/` は
`vcenter_event_assistant_plugin_api.testing` のハーネスを使っている。`run_collect()` は
`start` → `collect` → `stop` を回したうえで、バッチをアプリと同一の規則で検証し
（warning でも落ちる）、vCenter 接続のリークと `CreateContainerView` /
`CreateCollectorForEvents` の後始末漏れも検査する。

## 実装するところ

`src/$package/__init__.py` の `$method()` だけである。以下は基底クラスが引き受ける。

- クラス属性からの `CollectorManifest` の生成（`data_kinds` の導出を含む）
- vCenter 接続の open / close
- ブロッキング処理のスレッド退避（キャンセルされてもセッションを取り残さない）
- `MOCK_MODE=true` のときの合成データ
- `CollectionBatch` の組み立て$cursor_note

## ビルドとインストール

```bash
uv build
```

できた wheel をアプリの **Settings > プラグイン**からアップロードし、反映・有効化する。
外部プラグインは既定で無効なので、アップロード後に有効化が必要である。

## 気をつけること

| 項目 | 理由 |
|---|---|
| entry point 名と `manifest.id` を一致させる | ずれると `configured plugin is not installed` として failed になる |
| タイムスタンプは必ず timezone-aware | naive だとバッチが**丸ごと**拒否される |
| 設定値は `config` ヘルパ経由で読む | 環境変数由来は常に `str`、TOML 由来は TOML の型 |
| `print` ではなく `get_plugin_logger()` | stdout はワーカーのプロトコル専用である |
| 機密は環境変数から読む | TOML や DB に置かない |
| `vmware_key` は情報源の自然キーを使う | ハッシュだと重複排除でイベントが静かに消える |

詳細は
[docs/collector-plugin-authoring.md](https://github.com/t-m0riyama/vcenter-event-assistant/blob/main/docs/collector-plugin-authoring.md)
を参照。
''')

_CURSOR_NOTE = "\n- カーソルの decode と前進（空のバッチでも前進する）"


def render(
    *,
    distribution: str,
    plugin_id: str,
    kind: str,
    display_name: str | None = None,
) -> dict[str, str]:
    """生成するファイルを ``相対パス -> 内容`` で返す（書き込みはしない）。"""
    if kind not in ("metric", "event"):
        raise ScaffoldError(f"unknown kind: {kind!r}; use 'metric' or 'event'")
    distribution = normalize_distribution(distribution)
    plugin_id = _check_plugin_id(plugin_id)
    package = package_name(distribution)
    collector_class = class_name(distribution)
    label = display_name or distribution.replace("-", " ").title()

    values = {
        "distribution": distribution,
        "plugin_id": plugin_id,
        "package": package,
        "class_name": collector_class,
        "display_name": label,
        "requirement": PLUGIN_API_REQUIREMENT,
        "requirement_vmware": PLUGIN_API_REQUIREMENT.replace(
            "plugin-api", "plugin-api[vmware]", 1
        ),
        "metric_constant": "SAMPLE_METRIC",
        # メトリクスキーはプラグイン ID を接頭辞にすると衝突しにくい。
        "metric_key": f"{plugin_id}.sample",
        "method": "sample" if kind == "metric" else "fetch",
        "cursor_note": "" if kind == "metric" else _CURSOR_NOTE,
    }

    module = _METRIC_MODULE if kind == "metric" else _EVENT_MODULE
    test = _METRIC_TEST if kind == "metric" else _EVENT_TEST
    return {
        "pyproject.toml": _PYPROJECT.substitute(values),
        ".gitignore": _GITIGNORE,
        "README.md": _README.substitute(values),
        f"src/{package}/__init__.py": module.substitute(values),
        "tests/test_collector.py": test.substitute(values),
    }


def write_project(
    files: dict[str, str], target: Path, *, force: bool = False
) -> list[Path]:
    """生成物を書き出す。既存ファイルは ``force`` でなければ上書きしない。"""
    written: list[Path] = []
    existing = [
        name for name in files if (target / name).exists()
    ]
    if existing and not force:
        raise ScaffoldError(
            f"{target} already contains {', '.join(sorted(existing))}; "
            "pass --force to overwrite"
        )
    for name, content in sorted(files.items()):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vcenter_event_assistant_plugin_api.scaffold",
        description="Generate a collector plugin project for vCenter Event Assistant.",
    )
    parser.add_argument(
        "distribution",
        help="Distribution name, e.g. my-sensor-collector.",
    )
    parser.add_argument(
        "--id",
        dest="plugin_id",
        default=None,
        help="Plugin id (manifest.id and the entry point name). Defaults to the "
        "distribution name.",
    )
    parser.add_argument(
        "--kind",
        choices=("metric", "event"),
        default="metric",
        help="Whether the collector emits metrics or events (default: metric).",
    )
    parser.add_argument(
        "--name",
        dest="display_name",
        default=None,
        help="Human readable name shown in the management screen.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Directory to create (default: ./<distribution>).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        distribution = normalize_distribution(args.distribution)
        files = render(
            distribution=distribution,
            plugin_id=args.plugin_id or default_plugin_id(distribution),
            kind=args.kind,
            display_name=args.display_name,
        )
        target = Path(args.out) if args.out else Path(distribution)
        written = write_project(files, target, force=args.force)
    except ScaffoldError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    for path in written:
        print(path)
    package = package_name(distribution)
    print(
        f"\ncreated {target}\n"
        f"  next: cd {target} && uv sync && uv run pytest -q\n"
        f"  then implement {args.kind == 'metric' and 'sample()' or 'fetch()'} "
        f"in src/{package}/__init__.py"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - プロセスエントリ
    raise SystemExit(main())
