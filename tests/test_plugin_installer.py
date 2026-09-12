"""動的インストール（プラグイン管理フェーズ 3）。

実際に ``uv pip install --target`` を走らせる経路は、テスト用に組み立てた wheel を
使って検証する。ネットワークへ出ないよう、アップロード経路は ``--no-index`` で動く。
"""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.plugins.installer import (
    PluginInstallError,
    install_plugin,
    normalize_distribution,
    parse_requirement,
    parse_upload_filename,
    uninstall_plugin,
)
from vcenter_event_assistant.plugins.remote import plugin_search_paths
from vcenter_event_assistant.services.plugin_installs import wait_for_installs
from vcenter_event_assistant.settings import Settings, get_settings

_COLLECTOR_MODULE = '''
from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectorManifest,
    MetricDefinition,
)


class Collector:
    manifest = CollectorManifest(
        "example.temperature",
        "Example Temperature",
        "0.1.0",
        data_kinds=frozenset({"metric"}),
        metric_definitions=(
            MetricDefinition(
                "example.host.temperature_c", "Temperature", "C", "HostSystem"
            ),
        ),
    )

    async def start(self):
        return None

    async def stop(self):
        return None

    async def collect(self, context):
        return CollectionBatch()


def build_collector():
    return Collector()
'''


def _record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"{name},sha256={digest.decode()},{len(data)}"


def build_wheel(
    *,
    distribution: str = "example-collector",
    version: str = "0.1.0",
    with_entry_point: bool = True,
    requires: tuple[str, ...] = (),
    module_body: str | None = None,
) -> bytes:
    """最小限の PEP 427 wheel をメモリ上に組み立てる。"""
    module_name = "example_collector"
    dist_info = f"{distribution.replace('-', '_')}-{version}.dist-info"
    requires_lines = "".join(f"Requires-Dist: {item}\n" for item in requires)
    files: dict[str, bytes] = {
        f"{module_name}.py": (module_body or _COLLECTOR_MODULE).encode(),
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n"
            f"{requires_lines}"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    if with_entry_point:
        files[f"{dist_info}/entry_points.txt"] = (
            b"[vcenter_event_assistant.collectors]\n"
            b"example.temperature = example_collector:build_collector\n"
        )

    record = "\n".join(_record_line(name, data) for name, data in files.items())
    record += f"\n{dist_info}/RECORD,,\n"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr(f"{dist_info}/RECORD", record)
    return buffer.getvalue()


@pytest.fixture
def wheel_path(tmp_path):
    path = tmp_path / "example_collector-0.1.0-py3-none-any.whl"
    path.write_bytes(build_wheel())
    return path


@pytest.fixture
def plugin_settings(tmp_path):
    return Settings(plugin_dir=str(tmp_path / "plugins"))


# --- 入力検証 -------------------------------------------------------------


def test_parse_requirement_accepts_name_and_pinned_version() -> None:
    assert parse_requirement("Example_Collector") == ("example-collector", None)
    assert parse_requirement("example-collector==1.2.3") == (
        "example-collector",
        "1.2.3",
    )


@pytest.mark.parametrize(
    "requirement",
    [
        "example --index-url http://evil",
        "example; os.system('x')",
        "-e .",
        "https://evil.example.com/pkg.whl",
        "example>=1.0",
        "",
    ],
)
def test_parse_requirement_rejects_injection_and_loose_specifiers(
    requirement: str,
) -> None:
    """uv へ任意のフラグや URL が渡らないよう、厳格に拒否する。"""
    with pytest.raises(PluginInstallError):
        parse_requirement(requirement)


def test_parse_upload_filename_reads_distribution_and_version() -> None:
    assert parse_upload_filename("example_collector-0.1.0-py3-none-any.whl") == (
        "example-collector",
        "0.1.0",
    )
    assert parse_upload_filename("example_collector-0.1.0.tar.gz") == (
        "example-collector",
        "0.1.0",
    )


@pytest.mark.parametrize(
    "filename",
    [
        "../escape-1.0-py3-none-any.whl",
        "nested/path-1.0-py3-none-any.whl",
        "plugin.zip",
        "plugin.exe",
        "noversion.whl",
    ],
)
def test_parse_upload_filename_rejects_paths_and_other_types(filename: str) -> None:
    with pytest.raises(PluginInstallError):
        parse_upload_filename(filename)


def test_normalize_distribution_follows_pep503() -> None:
    assert normalize_distribution("Example_.-Collector") == "example-collector"


# --- インストール本体 -----------------------------------------------------


async def test_install_from_wheel_lays_out_per_version_directory(
    plugin_settings, wheel_path
) -> None:
    outcome = await install_plugin(
        plugin_settings, source=str(wheel_path), from_index=False
    )
    assert outcome.distribution == "example-collector"
    assert outcome.version == "0.1.0"
    assert outcome.collector_ids == ("example.temperature",)
    assert outcome.install_path.endswith("example-collector/0.1.0")
    # ワーカーの sys.path に載る形で配置されている。
    assert plugin_search_paths(plugin_settings.plugin_dir) == [outcome.install_path]
    # ステージング用ディレクトリは残さない。
    assert not (Path(plugin_settings.plugin_dir) / ".staging").exists()


async def test_install_rolls_back_when_no_collector_entry_point(
    plugin_settings, tmp_path
) -> None:
    wheel = tmp_path / "example_collector-0.1.0-py3-none-any.whl"
    wheel.write_bytes(build_wheel(with_entry_point=False))

    with pytest.raises(PluginInstallError, match="no 'vcenter_event_assistant"):
        await install_plugin(plugin_settings, source=str(wheel), from_index=False)

    # ロールバック: ディレクトリが残っていない。
    assert plugin_search_paths(plugin_settings.plugin_dir) == []


async def test_install_rolls_back_when_the_package_is_not_installable(
    plugin_settings, tmp_path
) -> None:
    broken = tmp_path / "example_collector-0.1.0-py3-none-any.whl"
    broken.write_bytes(b"not a wheel at all")
    with pytest.raises(PluginInstallError):
        await install_plugin(plugin_settings, source=str(broken), from_index=False)
    assert plugin_search_paths(plugin_settings.plugin_dir) == []


async def test_reinstalling_the_same_version_replaces_the_directory(
    plugin_settings, wheel_path
) -> None:
    first = await install_plugin(
        plugin_settings, source=str(wheel_path), from_index=False
    )
    second = await install_plugin(
        plugin_settings, source=str(wheel_path), from_index=False
    )
    assert first.install_path == second.install_path
    assert plugin_search_paths(plugin_settings.plugin_dir) == [second.install_path]


async def test_plugin_declaring_the_api_package_installs_offline(
    plugin_settings, tmp_path
) -> None:
    """`vcenter-event-assistant-plugin-api` を宣言した正しいプラグインが、
    ネットワーク無しのアップロード経路でインストールできること。

    この API パッケージはアプリ本体の依存として必ず存在し、ワーカーの sys.path から
    見えるため再インストールは不要である。依存解決を有効にしたままだとオフラインでは
    解決できず、ドキュメントどおりに書かれたプラグインが一切入らなくなる。
    """
    wheel = tmp_path / "example_collector-0.1.0-py3-none-any.whl"
    wheel.write_bytes(
        build_wheel(requires=("vcenter-event-assistant-plugin-api>=1.0.0,<2",))
    )
    outcome = await install_plugin(
        plugin_settings, source=str(wheel), from_index=False
    )
    assert outcome.collector_ids == ("example.temperature",)


async def test_install_rolls_back_when_a_dependency_is_missing(
    plugin_settings, tmp_path
) -> None:
    """オフラインでは依存を入れないため、本当に依存が要るプラグインは
    インストール直後の検証で import に失敗し、ロールバックされる（黙って壊れない）。
    """
    wheel = tmp_path / "example_collector-0.1.0-py3-none-any.whl"
    wheel.write_bytes(
        build_wheel(
            requires=("a-package-that-does-not-exist-anywhere",),
            module_body="import a_package_that_does_not_exist_anywhere\n",
        )
    )
    with pytest.raises(PluginInstallError, match="ModuleNotFoundError"):
        await install_plugin(plugin_settings, source=str(wheel), from_index=False)
    assert plugin_search_paths(plugin_settings.plugin_dir) == []


async def test_index_install_is_refused_unless_explicitly_enabled(
    plugin_settings,
) -> None:
    with pytest.raises(PluginInstallError, match="disabled"):
        await install_plugin(
            plugin_settings, source="example-collector", from_index=True
        )


async def test_uninstall_removes_the_distribution_directory(
    plugin_settings, wheel_path
) -> None:
    await install_plugin(plugin_settings, source=str(wheel_path), from_index=False)
    assert uninstall_plugin(plugin_settings, "Example_Collector") is True
    assert plugin_search_paths(plugin_settings.plugin_dir) == []
    # 2 回目は何も消さない。
    assert uninstall_plugin(plugin_settings, "example-collector") is False


@pytest.mark.parametrize("distribution", ["..", "../../etc", "a/b", ""])
def test_uninstall_rejects_path_traversal(plugin_settings, distribution: str) -> None:
    with pytest.raises(PluginInstallError):
        uninstall_plugin(plugin_settings, distribution)


# --- API ------------------------------------------------------------------


def _enable_management(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("VEA_PLUGIN_MANAGEMENT_ENABLED", "true")
    monkeypatch.setenv("VEA_PLUGIN_DIR", str(tmp_path / "plugins"))
    get_settings.cache_clear()


async def test_install_endpoints_are_hidden_when_management_is_disabled(
    client: AsyncClient,
) -> None:
    listed = await client.get("/api/plugins/installed")
    uploaded = await client.post(
        "/api/plugins/installed/upload",
        files={"file": ("example_collector-0.1.0-py3-none-any.whl", b"x")},
    )
    assert listed.status_code == 404
    assert uploaded.status_code == 404


async def test_upload_install_flow_reports_status(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _enable_management(monkeypatch, tmp_path)
    response = await client.post(
        "/api/plugins/installed/upload",
        files={
            "file": (
                "example_collector-0.1.0-py3-none-any.whl",
                build_wheel(),
                "application/octet-stream",
            )
        },
    )
    assert response.status_code == 202
    assert response.json()["plugins"][0]["status"] == "installing"

    await wait_for_installs()

    listed = (await client.get("/api/plugins/installed")).json()
    entry = listed["plugins"][0]
    assert entry["distribution"] == "example-collector"
    assert entry["version"] == "0.1.0"
    assert entry["status"] == "installed"
    assert entry["source"] == "upload"
    assert entry["error"] is None

    removed = await client.delete("/api/plugins/installed/example-collector")
    assert removed.status_code == 200
    assert removed.json()["plugins"] == []


async def test_upload_install_records_failure_without_raising(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _enable_management(monkeypatch, tmp_path)
    response = await client.post(
        "/api/plugins/installed/upload",
        files={
            "file": (
                "example_collector-0.1.0-py3-none-any.whl",
                build_wheel(with_entry_point=False),
                "application/octet-stream",
            )
        },
    )
    assert response.status_code == 202
    await wait_for_installs()

    entry = (await client.get("/api/plugins/installed")).json()["plugins"][0]
    assert entry["status"] == "failed"
    assert "entry point" in entry["error"]


async def test_upload_rejects_unsupported_file_types(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _enable_management(monkeypatch, tmp_path)
    response = await client.post(
        "/api/plugins/installed/upload",
        files={"file": ("payload.zip", b"whatever", "application/zip")},
    )
    assert response.status_code == 422


async def test_upload_rejects_an_empty_file(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _enable_management(monkeypatch, tmp_path)
    response = await client.post(
        "/api/plugins/installed/upload",
        files={"file": ("example_collector-0.1.0-py3-none-any.whl", b"")},
    )
    assert response.status_code == 422


async def test_index_install_endpoint_is_refused_when_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _enable_management(monkeypatch, tmp_path)
    response = await client.post(
        "/api/plugins/installed", json={"requirement": "example-collector==1.0"}
    )
    assert response.status_code == 409


async def test_uninstalling_an_unknown_distribution_is_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _enable_management(monkeypatch, tmp_path)
    response = await client.delete("/api/plugins/installed/nothing-here")
    assert response.status_code == 404
