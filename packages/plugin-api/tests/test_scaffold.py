"""スキャフォールドが生成するプロジェクト。

確かめたいのは「生成物が最初から正しい」ことである。とくに ``manifest.id`` は
entry point 名・manifest・メトリクスキーの 3 箇所に現れ、不一致は本番で
``configured plugin is not installed`` という遠い文言になって初めて露見する。
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from vcenter_event_assistant_plugin_api import __version__, scaffold


class TestNames:
    def test_normalizes_the_distribution_name(self) -> None:
        assert scaffold.normalize_distribution("My Sensor Collector") == "my-sensor-collector"
        assert scaffold.normalize_distribution("my_sensor_collector") == "my-sensor-collector"
        assert scaffold.normalize_distribution("  my--sensor  ") == "my-sensor"

    def test_trims_leading_and_trailing_separators(self) -> None:
        assert scaffold.normalize_distribution("-leading") == "leading"
        assert scaffold.normalize_distribution("trailing-") == "trailing"

    @pytest.mark.parametrize("name", ["", "-", "!!", "a b!c", "UPPER!"])
    def test_rejects_an_unusable_distribution_name(self, name: str) -> None:
        with pytest.raises(scaffold.ScaffoldError, match="invalid distribution name"):
            scaffold.normalize_distribution(name)

    def test_derives_the_package_and_class_names(self) -> None:
        assert scaffold.package_name("my-sensor-collector") == "my_sensor_collector"
        assert scaffold.package_name("acme.sensors") == "acme_sensors"
        assert scaffold.class_name("my-sensor-collector") == "MySensorCollector"

    def test_rejects_a_plugin_id_the_application_would_refuse(self) -> None:
        with pytest.raises(scaffold.ScaffoldError, match="invalid plugin id"):
            scaffold.render(
                distribution="ok-name", plugin_id="Not Valid", kind="metric"
            )

    def test_rejects_the_reserved_builtin_prefix(self) -> None:
        with pytest.raises(scaffold.ScaffoldError, match="reserved"):
            scaffold.render(
                distribution="ok-name", plugin_id="builtin.mine", kind="metric"
            )

    def test_rejects_an_unknown_kind(self) -> None:
        with pytest.raises(scaffold.ScaffoldError, match="unknown kind"):
            scaffold.render(distribution="ok-name", plugin_id="ok.id", kind="trace")


def _render(kind: str, plugin_id: str = "acme.sensor") -> dict[str, str]:
    return scaffold.render(
        distribution="acme-sensor-collector", plugin_id=plugin_id, kind=kind
    )


class TestRenderedProject:
    @pytest.mark.parametrize("kind", ["metric", "event"])
    def test_it_writes_the_expected_files(self, kind: str) -> None:
        assert set(_render(kind)) == {
            "pyproject.toml",
            ".gitignore",
            "README.md",
            "src/acme_sensor_collector/__init__.py",
            "tests/test_collector.py",
        }

    @pytest.mark.parametrize("kind", ["metric", "event"])
    def test_the_entry_point_name_equals_the_plugin_id(self, kind: str) -> None:
        files = _render(kind)
        pyproject = tomllib.loads(files["pyproject.toml"])
        entry_points = pyproject["project"]["entry-points"][
            "vcenter_event_assistant.collectors"
        ]
        assert list(entry_points) == ["acme.sensor"]
        assert entry_points["acme.sensor"] == "acme_sensor_collector:build_collector"
        assert 'PLUGIN_ID = "acme.sensor"' in files["src/acme_sensor_collector/__init__.py"]

    @pytest.mark.parametrize("kind", ["metric", "event"])
    def test_the_generated_code_is_syntactically_valid(self, kind: str) -> None:
        for name, content in _render(kind).items():
            if name.endswith(".py"):
                compile(content, name, "exec")

    @pytest.mark.parametrize("kind", ["metric", "event"])
    def test_it_never_imports_the_application(self, kind: str) -> None:
        """プラグインはアプリ本体を import しない規約。"""
        for name, content in _render(kind).items():
            if name.endswith(".py"):
                assert "vcenter_event_assistant." not in content or (
                    "vcenter_event_assistant_plugin_api" in content
                )
                assert "import vcenter_event_assistant\n" not in content

    def test_it_pins_the_current_plugin_api_minor(self) -> None:
        pyproject = tomllib.loads(_render("metric")["pyproject.toml"])
        minor = ".".join(__version__.split(".")[:2])
        assert pyproject["project"]["dependencies"] == [
            f"vcenter-event-assistant-plugin-api>={minor},<2"
        ]

    def test_only_the_dev_group_asks_for_pyvmomi(self) -> None:
        """実行時はワーカーの pyVmomi を使うので、本体の依存にはしない。"""
        pyproject = tomllib.loads(_render("metric")["pyproject.toml"])
        assert all(
            "[vmware]" not in requirement
            for requirement in pyproject["project"]["dependencies"]
        )
        assert any(
            "[vmware]" in requirement
            for requirement in pyproject["dependency-groups"]["dev"]
        )

    def test_the_metric_key_is_namespaced_by_the_plugin_id(self) -> None:
        module = _render("metric")["src/acme_sensor_collector/__init__.py"]
        assert 'key="acme.sensor.sample"' in module

    def test_the_event_template_uses_the_natural_key(self) -> None:
        module = _render("event")["src/acme_sensor_collector/__init__.py"]
        assert "vmware_key=int(key)" in module
        # ハッシュ由来のキーを勧めてはならない（重複排除で静かに消える）。
        assert "stable_int31" not in module


class TestWriteProject:
    def test_it_creates_the_tree(self, tmp_path: Path) -> None:
        written = scaffold.write_project(_render("metric"), tmp_path / "out")
        assert (tmp_path / "out" / "src" / "acme_sensor_collector" / "__init__.py").is_file()
        assert len(written) == 5

    def test_it_refuses_to_overwrite_by_default(self, tmp_path: Path) -> None:
        files = _render("metric")
        scaffold.write_project(files, tmp_path / "out")
        with pytest.raises(scaffold.ScaffoldError, match="--force"):
            scaffold.write_project(files, tmp_path / "out")
        scaffold.write_project(files, tmp_path / "out", force=True)


class TestCli:
    def test_it_generates_a_runnable_project(self, tmp_path: Path) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "vcenter_event_assistant_plugin_api.scaffold",
                "My Sensor Collector",
                "--out",
                str(tmp_path / "proj"),
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert "implement sample()" in completed.stdout
        assert (tmp_path / "proj" / "src" / "my_sensor_collector" / "__init__.py").is_file()

    def test_it_reports_a_bad_name_without_a_traceback(self, tmp_path: Path) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "vcenter_event_assistant_plugin_api.scaffold",
                "!!!",
                "--out",
                str(tmp_path / "proj"),
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 2
        assert "error: invalid distribution name" in completed.stderr
        assert "Traceback" not in completed.stderr


@pytest.mark.parametrize("kind", ["metric", "event"])
def test_the_generated_tests_pass_out_of_the_box(tmp_path: Path, kind: str) -> None:
    """受け入れ条件そのもの。**アプリを一度も起動せずに** pytest が通ること。

    生成物を別プロセスの pytest で走らせる。依存の解決はここでは行わず、
    このリポジトリの環境（plugin-api と pyVmomi が入っている）を使う。
    """
    project = tmp_path / kind
    scaffold.write_project(
        scaffold.render(
            distribution="acme-sensor-collector", plugin_id="acme.sensor", kind=kind
        ),
        project,
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=project,
        capture_output=True,
        text=True,
        env={**_env_with_src(project)},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _env_with_src(project: Path) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(project / "src")
    return env
