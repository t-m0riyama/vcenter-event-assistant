"""外部プラグインのプロセス分離（プラグイン管理フェーズ 2）。

実際にワーカープロセスを起動するため、テスト用のプラグイン配布物を tmp_path に
組み立てる。``uv build`` は使わず ``.dist-info`` を直接書くことで、CI での実行時間と
ネットワーク依存を避ける。
"""

from __future__ import annotations

import asyncio
import textwrap

import pytest
from vcenter_event_assistant_plugin_api import CollectionContext
from vcenter_event_assistant_plugin_api.testing import (
    make_context,
    make_target,
    stub_plugin_source,
)

from vcenter_event_assistant.plugins.remote import (
    CollectorWorkerError,
    build_remote_plugins,
    plugin_search_paths,
)
from vcenter_event_assistant.plugins.wire import ConnectionParams

COLLECT_TIMEOUT = 30.0

def _install_test_plugin(root, *, distribution="example-collector", version="0.1.0"):
    """``<root>/<distribution>/<version>/`` に import 可能な配布物を書き出す。"""
    target = root / distribution / version
    target.mkdir(parents=True)
    (target / "example_collector.py").write_text(
        stub_plugin_source(
            fault_env_var="VEA_TEST_PLUGIN_MODE",
            noisy_stdout=True,
            raise_message="do-not-leak-secret-value",
        ),
        encoding="utf-8",
    )

    dist_info = target / f"{distribution.replace('-', '_')}-{version}.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        textwrap.dedent(
            f"""\
            Metadata-Version: 2.1
            Name: {distribution}
            Version: {version}
            """
        ),
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        "[vcenter_event_assistant.collectors]\n"
        "example.temperature = example_collector:build_collector\n",
        encoding="utf-8",
    )
    (dist_info / "RECORD").write_text("", encoding="utf-8")
    return target


@pytest.fixture
def plugin_dir(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    _install_test_plugin(root)
    return str(root)


def _context(*, mock_mode: bool = True) -> CollectionContext:
    """ワーカーへ送る収集コンテキスト。

    ``open_vcenter_connection`` はワーカー側で組み立て直される（親から子へ渡るのは
    接続情報だけで、呼び出し可能オブジェクトは渡せない）ため、ここで指定するものは
    使われない。
    """
    return make_context(
        target=make_target(name="Alpha", host="vc.example.com", username="user"),
        config={"sensor": "system-board"},
        mock_mode=mock_mode,
    )


def _params() -> ConnectionParams:
    return ConnectionParams(
        host="vc.example.com",
        protocol="https",
        port=443,
        username="user",
        password="do-not-leak-secret-value",
        verify_ssl=True,
    )


def test_plugin_search_paths_lists_distribution_versions(plugin_dir, tmp_path) -> None:
    paths = plugin_search_paths(plugin_dir)
    assert len(paths) == 1
    assert paths[0].endswith("example-collector/0.1.0")
    # ディレクトリが無い / 未設定でも失敗しない。
    assert plugin_search_paths(str(tmp_path / "missing")) == []
    assert plugin_search_paths(None) == []


def test_discovery_returns_manifest_without_importing_in_parent(plugin_dir) -> None:
    import sys

    plugins, failures = build_remote_plugins(plugin_dir)
    assert failures == {}
    assert [p.manifest.id for p in plugins] == ["example.temperature"]
    manifest = plugins[0].manifest
    assert manifest.data_kinds == frozenset({"metric"})
    assert manifest.metric_definitions[0].key == "example.host.temperature_c"
    # プラグインは親プロセスへ import されていない（分離が効いている証拠）。
    assert "example_collector" not in sys.modules


async def test_remote_collect_round_trip(plugin_dir) -> None:
    plugins, _ = build_remote_plugins(plugin_dir)
    plugin = plugins[0]
    await plugin.start()
    try:
        batch = await plugin.collect_with_connection(
            _context(), _params(), timeout=COLLECT_TIMEOUT
        )
    finally:
        await plugin.stop()

    assert batch.next_cursor == "cursor-1"
    assert len(batch.metrics) == 1
    sample = batch.metrics[0]
    assert sample.metric_key == "example.host.temperature_c"
    assert sample.value == 42.5
    # context がワーカー側へ正しく渡っている。
    assert sample.entity_name == "Alpha"
    assert sample.sampled_at.tzinfo is not None


async def test_plugin_stdout_does_not_corrupt_the_protocol(plugin_dir) -> None:
    """プラグインの print で stdout が汚れても応答は壊れない。"""
    plugins, _ = build_remote_plugins(plugin_dir)
    plugin = plugins[0]
    try:
        first = await plugin.collect_with_connection(
            _context(), _params(), timeout=COLLECT_TIMEOUT
        )
        second = await plugin.collect_with_connection(
            _context(), _params(), timeout=COLLECT_TIMEOUT
        )
    finally:
        await plugin.stop()
    assert first.next_cursor == second.next_cursor == "cursor-1"


async def test_hanging_plugin_times_out_and_worker_is_killed(
    plugin_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VEA_TEST_PLUGIN_MODE", "hang")
    plugins, _ = build_remote_plugins(plugin_dir)
    plugin = plugins[0]
    with pytest.raises(asyncio.TimeoutError):
        await plugin.collect_with_connection(_context(), _params(), timeout=2)
    assert plugin._worker.is_running is False


async def test_worker_recovers_after_being_killed(
    plugin_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kill 後も、次の実行で新しいワーカーが起動して復帰する。"""
    monkeypatch.setenv("VEA_TEST_PLUGIN_MODE", "hang")
    plugins, _ = build_remote_plugins(plugin_dir)
    plugin = plugins[0]
    with pytest.raises(asyncio.TimeoutError):
        await plugin.collect_with_connection(_context(), _params(), timeout=2)

    monkeypatch.setenv("VEA_TEST_PLUGIN_MODE", "ok")
    try:
        batch = await plugin.collect_with_connection(
            _context(), _params(), timeout=COLLECT_TIMEOUT
        )
    finally:
        await plugin.stop()
    assert batch.next_cursor == "cursor-1"


async def test_crashing_worker_surfaces_an_error(
    plugin_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VEA_TEST_PLUGIN_MODE", "crash")
    plugins, _ = build_remote_plugins(plugin_dir)
    plugin = plugins[0]
    with pytest.raises(CollectorWorkerError):
        await plugin.collect_with_connection(
            _context(), _params(), timeout=COLLECT_TIMEOUT
        )
    assert plugin._worker.is_running is False


async def test_plugin_exception_does_not_leak_details(
    plugin_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VEA_TEST_PLUGIN_MODE", "raise")
    plugins, _ = build_remote_plugins(plugin_dir)
    plugin = plugins[0]
    try:
        with pytest.raises(CollectorWorkerError) as excinfo:
            await plugin.collect_with_connection(
                _context(), _params(), timeout=COLLECT_TIMEOUT
            )
    finally:
        await plugin.stop()
    # 例外文言は認証情報やレスポンス本文を含みうるため、型名だけを返す。
    assert str(excinfo.value) == "RuntimeError"
    assert "do-not-leak-secret-value" not in str(excinfo.value)


def test_broken_entry_point_is_reported_as_a_failure(tmp_path) -> None:
    root = tmp_path / "plugins"
    target = root / "broken" / "1.0"
    target.mkdir(parents=True)
    dist_info = target / "broken-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: broken\nVersion: 1.0\n", encoding="utf-8"
    )
    (dist_info / "entry_points.txt").write_text(
        "[vcenter_event_assistant.collectors]\n"
        "broken.collector = does_not_exist:build\n",
        encoding="utf-8",
    )
    (dist_info / "RECORD").write_text("", encoding="utf-8")

    plugins, failures = build_remote_plugins(str(root))
    assert plugins == []
    assert "broken.collector" in failures
    assert "ModuleNotFoundError" in failures["broken.collector"]


def test_registry_registers_discovered_plugins_as_remote(plugin_dir) -> None:
    """検出されたプラグインはレジストリに載るが、外部由来は既定で無効である。"""
    from vcenter_event_assistant.plugins.registry import build_collector_registry
    from vcenter_event_assistant.plugins.remote import RemoteCollectorPlugin
    from vcenter_event_assistant.settings import Settings

    registry = build_collector_registry(Settings(plugin_dir=plugin_dir))
    registration = registry.get("example.temperature")
    assert registration is not None
    assert registration.source == "entry_point:example.temperature"
    assert registration.status == "disabled"
    assert isinstance(registration.plugin, RemoteCollectorPlugin)

    enabled_registry = build_collector_registry(
        Settings(plugin_dir=plugin_dir),
        db_overrides={"example.temperature": {"enabled": True}},
    )
    assert enabled_registry.get("example.temperature").status == "enabled"
    # 有効化すると、宣言したメトリクスがカタログに載る。
    assert (
        "example.temperature",
        "example.host.temperature_c",
    ) in {
        (plugin_id, definition.key)
        for plugin_id, definition in enabled_registry.metric_catalog()
    }


def test_registry_skips_the_worker_when_nothing_is_installed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """検出対象が無いときはワーカーを起動しない（起動・テストのコストを避ける）。"""
    from vcenter_event_assistant.plugins import registry as registry_module
    from vcenter_event_assistant.settings import Settings

    monkeypatch.setattr(registry_module, "entry_points", lambda **_: [])

    def _fail(*args, **kwargs):
        raise AssertionError("discovery worker must not be spawned")

    monkeypatch.setattr(
        "vcenter_event_assistant.plugins.remote.build_remote_plugins", _fail
    )
    registry = registry_module.build_collector_registry(
        Settings(plugin_dir=str(tmp_path / "absent"))
    )
    assert registry.enabled()


def test_discovery_failure_is_isolated_into_a_failed_registration(
    plugin_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """検出が丸ごと失敗してもアプリは起動でき、失敗が可視化される。"""
    from vcenter_event_assistant.plugins.registry import build_collector_registry
    from vcenter_event_assistant.settings import Settings

    def _boom(*args, **kwargs):
        raise CollectorWorkerError("plugin discovery timed out")

    monkeypatch.setattr(
        "vcenter_event_assistant.plugins.remote.build_remote_plugins", _boom
    )
    registry = build_collector_registry(Settings(plugin_dir=plugin_dir))
    failure = registry.get("discovery")
    assert failure is not None
    assert failure.status == "failed"
    assert "plugin discovery failed" in failure.error
    # builtin は影響を受けない。
    assert registry.get("builtin.vcenter.events").status == "enabled"


def test_connection_params_repr_hides_the_password() -> None:
    """ログや例外文字列にパスワードが乗らないことを保証する。"""
    text = repr(_params())
    assert "do-not-leak-secret-value" not in text
    assert "password=***" in text
