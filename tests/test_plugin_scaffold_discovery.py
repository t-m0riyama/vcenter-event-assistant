"""スキャフォールドの生成物が、アプリの検出経路をそのまま通ること。

生成物の単体テストは plugin-api 側にある。ここで確かめるのはアプリ側との接続、
つまり**別プロセスのワーカーが entry point を読み込み、manifest を返せる**ことである。
ここがずれると、作者の手元では通るのにアプリでは `failed` になる。

``uv build`` は使わず ``.dist-info`` を直接書く。CI での実行時間とネットワーク依存を
避けるためで、``test_plugin_worker.py`` と同じ手法である。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from vcenter_event_assistant_plugin_api import scaffold

from vcenter_event_assistant.plugins.remote import build_remote_plugins

KINDS = ("metric", "event")


def _install_generated_plugin(root: Path, kind: str, *, plugin_id: str) -> None:
    distribution = "acme-sensor-collector"
    files = scaffold.render(
        distribution=distribution, plugin_id=plugin_id, kind=kind
    )
    target = root / distribution / "0.1.0"
    package = scaffold.package_name(distribution)

    # 生成されたソースだけを配置する（tests や README はインストール対象ではない）。
    module_dir = target / package
    module_dir.mkdir(parents=True)
    (module_dir / "__init__.py").write_text(
        files[f"src/{package}/__init__.py"], encoding="utf-8"
    )

    dist_info = target / f"{package}-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        textwrap.dedent(
            f"""\
            Metadata-Version: 2.1
            Name: {distribution}
            Version: 0.1.0
            """
        ),
        encoding="utf-8",
    )
    # entry point 名は生成された pyproject.toml と同じ組み立て方にする。
    (dist_info / "entry_points.txt").write_text(
        "[vcenter_event_assistant.collectors]\n"
        f"{plugin_id} = {package}:build_collector\n",
        encoding="utf-8",
    )
    (dist_info / "RECORD").write_text("", encoding="utf-8")


@pytest.mark.parametrize("kind", KINDS)
def test_a_generated_plugin_is_discovered_with_its_manifest(
    tmp_path: Path, kind: str
) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    _install_generated_plugin(root, kind, plugin_id="acme.sensor")

    plugins, failures = build_remote_plugins(str(root))

    assert failures == {}
    assert [plugin.manifest.id for plugin in plugins] == ["acme.sensor"]
    manifest = plugins[0].manifest
    # entry point 名と manifest.id が一致していること。ここがスキャフォールドの主目的。
    assert plugins[0].entry_point == manifest.id
    assert manifest.api_version == 1
    expected_kind = "metric" if kind == "metric" else "event"
    assert manifest.data_kinds == frozenset({expected_kind})
    if kind == "metric":
        assert [d.key for d in manifest.metric_definitions] == ["acme.sensor.sample"]


def test_a_generated_plugin_registers_and_can_be_enabled(tmp_path: Path) -> None:
    """レジストリに載り、外部由来なので既定では無効であること。"""
    from vcenter_event_assistant.plugins.registry import build_collector_registry
    from vcenter_event_assistant.settings import Settings

    root = tmp_path / "plugins"
    root.mkdir()
    _install_generated_plugin(root, "metric", plugin_id="acme.sensor")

    registry = build_collector_registry(Settings(plugin_dir=str(root)))
    registration = registry.get("acme.sensor")
    assert registration is not None
    assert registration.status == "disabled"

    enabled = build_collector_registry(
        Settings(plugin_dir=str(root)),
        db_overrides={"acme.sensor": {"enabled": True}},
    )
    assert enabled.get("acme.sensor").status == "enabled"
    assert ("acme.sensor", "acme.sensor.sample") in {
        (plugin_id, definition.key)
        for plugin_id, definition in enabled.metric_catalog()
    }
