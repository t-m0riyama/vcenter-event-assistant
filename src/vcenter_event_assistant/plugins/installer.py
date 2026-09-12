"""Dynamic installation of collector plugin distributions.

``uv pip install --target`` で ``<plugin_dir>/<distribution>/<version>/`` へ配布物ごとに
隔離して展開する。``--target`` にはアンインストール機能が無いため、配布物単位で
ディレクトリを分けることで「削除するだけ」でアンインストールとロールバックが完結する。

インストールしたコードはワーカープロセスで実行される（``plugins/worker.py``）。
インストール操作そのものは任意コード実行を招きうるため、API 層で
``VEA_PLUGIN_MANAGEMENT_ENABLED`` によるゲートを必ず通すこと。
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from vcenter_event_assistant.plugins.remote import discover_collectors_at
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
INSTALL_TIMEOUT_SECONDS = 600.0

_WHEEL_SUFFIX = ".whl"
_SDIST_SUFFIX = ".tar.gz"
# 任意のフラグ注入を防ぐため、requirement は名前と省略可能な固定バージョンのみ許す。
_NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
_NAME_RE = re.compile(rf"^{_NAME_PATTERN}$")
_REQUIREMENT_RE = re.compile(
    rf"^(?P<name>{_NAME_PATTERN})(?:==(?P<version>[A-Za-z0-9][A-Za-z0-9.*+!-]{{0,31}}))?$"
)
_STAGING_DIR = ".staging"


class PluginInstallError(RuntimeError):
    """インストールを中止した（利用者に提示してよいメッセージを持つ）。"""


@dataclass(frozen=True, slots=True)
class InstallOutcome:
    distribution: str
    version: str
    install_path: str
    collector_ids: tuple[str, ...]


def normalize_distribution(name: str) -> str:
    """PEP 503 の正規化名。ディレクトリ名と DB キーの双方に使う。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement(requirement: str) -> tuple[str, str | None]:
    """``name`` または ``name==version`` を検証して分解する。"""
    match = _REQUIREMENT_RE.fullmatch(requirement.strip())
    if match is None:
        raise PluginInstallError(
            "requirement must be '<name>' or '<name>==<version>'"
        )
    return normalize_distribution(match.group("name")), match.group("version")


def parse_upload_filename(filename: str) -> tuple[str, str]:
    """wheel / sdist のファイル名から配布物名とバージョンを取り出す。

    ファイル名はディレクトリ名の決定にしか使わないが、パス要素が混ざると
    書き込み先を逸脱しうるため厳格に検証する。
    """
    name = Path(filename).name
    if name != filename or "/" in filename or "\\" in filename:
        raise PluginInstallError("filename must not contain a path")
    if name.endswith(_WHEEL_SUFFIX):
        parts = name[: -len(_WHEEL_SUFFIX)].split("-")
        if len(parts) < 3:
            raise PluginInstallError("malformed wheel filename")
        return normalize_distribution(parts[0]), parts[1]
    if name.endswith(_SDIST_SUFFIX):
        stem = name[: -len(_SDIST_SUFFIX)]
        distribution, separator, version = stem.rpartition("-")
        if not separator or not distribution or not version:
            raise PluginInstallError("malformed sdist filename")
        return normalize_distribution(distribution), version
    raise PluginInstallError("only .whl and .tar.gz plugin packages are accepted")


def _uv_executable(settings: Settings) -> str:
    candidate = settings.uv_bin or shutil.which("uv")
    if not candidate:
        raise PluginInstallError(
            "the 'uv' executable was not found; plugin installation is unavailable"
        )
    return candidate


def _install_command(
    settings: Settings, target: Path, source: str, *, from_index: bool
) -> list[str]:
    command = [
        _uv_executable(settings),
        "pip",
        "install",
        "--target",
        str(target),
        "--python",
        _python_executable(),
    ]
    if from_index:
        if settings.plugin_index_url:
            command += ["--index-url", settings.plugin_index_url]
    elif not settings.plugin_allow_index_install:
        # アップロード経路は既定でネットワークへ出ないため、依存解決もできない。
        # `--no-deps` を付けないと、正しく `vcenter-event-assistant-plugin-api` を
        # 宣言したプラグインすら「解決できない」で失敗する。この API パッケージは
        # アプリ本体の依存として必ず存在し、ワーカーの sys.path から見えるので、
        # 再インストールする必要はない（別バージョンが載ると齟齬の元にもなる）。
        #
        # 他に依存を持つプラグインは、ここでは入らないまま素通りするが、直後の
        # 検証で entry point の import が ModuleNotFoundError になり、
        # ディレクトリごとロールバックされるため、黙って壊れた状態にはならない。
        command += ["--no-index", "--no-deps"]
    return command + [source]


def _python_executable() -> str:
    import sys

    return sys.executable


async def _run_install(command: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(), timeout=INSTALL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise PluginInstallError("installation timed out") from None
    if process.returncode != 0:
        output = (stdout or b"").decode(errors="replace").strip()
        logger.error("plugin installation failed rc=%s\n%s", process.returncode, output)
        # uv の出力は index URL などを含みうるため、末尾の要約だけを返す。
        tail = output.splitlines()[-1] if output else "unknown error"
        raise PluginInstallError(f"installation failed: {tail[:300]}")


def _installed_distribution(target: Path) -> tuple[str, str]:
    """展開先の ``*.dist-info`` から実際の配布物名とバージョンを読む。"""
    candidates = sorted(target.glob("*.dist-info"))
    if not candidates:
        raise PluginInstallError("the package did not install any distribution")
    stem = candidates[0].name[: -len(".dist-info")]
    distribution, separator, version = stem.rpartition("-")
    if not separator:
        raise PluginInstallError("could not determine the installed version")
    return normalize_distribution(distribution), version


def _plugin_root(settings: Settings) -> Path:
    return Path(settings.plugin_dir)


def _validate_provides_collectors(path: Path) -> tuple[str, ...]:
    """新しい配布物だけを対象に検出を走らせ、実際にコレクタを提供するか確かめる。"""
    discovered = discover_collectors_at([str(path)])
    failures = [item for item in discovered if "manifest" not in item]
    if failures:
        reasons = ", ".join(
            f"{item.get('name')}: {item.get('error')}" for item in failures
        )
        raise PluginInstallError(f"collector entry point failed to load ({reasons})")
    if not discovered:
        raise PluginInstallError(
            "the package provides no 'vcenter_event_assistant.collectors' entry point"
        )
    return tuple(str(item["manifest"]["id"]) for item in discovered)


async def install_plugin(
    settings: Settings, *, source: str, from_index: bool
) -> InstallOutcome:
    """1 配布物をインストールし、検証に失敗したらディレクトリごとロールバックする。

    Args:
        settings: アプリ設定。
        source: wheel/sdist のローカルパス、またはインデックス用 requirement。
        from_index: インデックスから取得するか。

    Returns:
        確定したインストール結果。
    """
    if from_index and not settings.plugin_allow_index_install:
        raise PluginInstallError(
            "installing from a package index is disabled (VEA_PLUGIN_ALLOW_INDEX_INSTALL)"
        )

    root = _plugin_root(settings)
    staging = root / _STAGING_DIR / uuid.uuid4().hex
    staging.mkdir(parents=True, exist_ok=True)
    try:
        await _run_install(
            _install_command(settings, staging, source, from_index=from_index)
        )
        distribution, version = await asyncio.to_thread(
            _installed_distribution, staging
        )
        collector_ids = await asyncio.to_thread(_validate_provides_collectors, staging)

        final = root / distribution / version
        await asyncio.to_thread(_replace_directory, staging, final)
    except BaseException:
        await asyncio.to_thread(shutil.rmtree, staging, True)
        raise
    finally:
        await asyncio.to_thread(_prune_staging_root, root)

    logger.info(
        "collector plugin installed distribution=%s version=%s collectors=%s",
        distribution,
        version,
        collector_ids,
    )
    return InstallOutcome(
        distribution=distribution,
        version=version,
        install_path=str(final),
        collector_ids=collector_ids,
    )


def _replace_directory(staging: Path, final: Path) -> None:
    """同一バージョンの再インストールでは、旧ディレクトリを置き換える。"""
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        shutil.rmtree(final)
    staging.replace(final)


def _prune_staging_root(root: Path) -> None:
    staging_root = root / _STAGING_DIR
    try:
        if staging_root.is_dir() and not any(staging_root.iterdir()):
            staging_root.rmdir()
    except OSError:  # pragma: no cover - 後始末のベストエフォート
        pass


def uninstall_plugin(settings: Settings, distribution: str) -> bool:
    """配布物のディレクトリを削除する。

    ``--target`` 方式のため、削除だけでアンインストールが完結する。

    Returns:
        実際に削除したかどうか。
    """
    # 正規化前の生入力を検証する。".." は正規化すると "-" になり、正規化後の
    # チェックだけでは不正な入力を素通りさせてしまう。
    if not _NAME_RE.fullmatch(distribution.strip()):
        raise PluginInstallError("invalid distribution name")
    normalized = normalize_distribution(distribution.strip())
    target = _plugin_root(settings) / normalized
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    logger.info("collector plugin uninstalled distribution=%s", normalized)
    return True
