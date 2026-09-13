"""パッケージの不変条件を機械的に守る。

方針を口約束にしないためのテストである。いずれも破ると広範囲に影響する。

1. 依存ゼロ（``import`` が第三者パッケージを引かない）
2. pyVmomi を遅延 import に閉じる
3. アプリ本体（``vcenter_event_assistant``）を import しない
4. ``PLUGIN_API_VERSION`` を安易に上げない
5. 型情報を配布する（``py.typed``）
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
from importlib import metadata

import vcenter_event_assistant_plugin_api as api

PACKAGE_ROOT = pathlib.Path(api.__file__).parent
SOURCE_FILES = sorted(PACKAGE_ROOT.rglob("*.py"))


def test_there_are_source_files_to_check() -> None:
    assert SOURCE_FILES, "走査対象が空ならこのファイルのテストは全て無意味になる"


def test_importing_the_package_does_not_pull_pyvmomi() -> None:
    """pyVmomi はアプリの依存であり、プラグイン側の import では読まれてはならない。

    必ず**新しいインタプリタ**で確かめる。アプリのテストと同じセッションで見ると、
    他のテストが先に pyVmomi を読み込んでいて結果が意味を失う。
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, vcenter_event_assistant_plugin_api\n"
            "loaded = sorted(m for m in sys.modules if m.split('.')[0] in {'pyVmomi', 'pyVim'})\n"
            "print(loaded)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "[]", completed.stdout


def test_no_module_imports_the_application() -> None:
    """「プラグインはアプリ本体を import しない」という規約の機械的強制。"""
    offenders: list[str] = []
    for path in SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == "vcenter_event_assistant" or name.startswith(
                    "vcenter_event_assistant."
                ):
                    offenders.append(f"{path.name}:{node.lineno} -> {name}")
    assert offenders == []


def test_pyvmomi_is_never_imported_at_module_level() -> None:
    """`vmware` サブモジュールが増えたときも、関数内 import に閉じること。"""
    offenders: list[str] = []
    for path in SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:  # モジュール直下だけを見る
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n.split(".")[0] in {"pyVmomi", "pyVim"} for n in names):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_the_distribution_declares_no_required_dependencies() -> None:
    """extra 由来を除いて依存が空であること。"""
    requires = metadata.requires("vcenter-event-assistant-plugin-api") or []
    required = [r for r in requires if "extra ==" not in r]
    assert required == []


def test_py_typed_is_present() -> None:
    assert (PACKAGE_ROOT / "py.typed").is_file()


def test_plugin_api_version_is_still_one() -> None:
    """上げるとアプリが既存の全プラグインを failed にする。

    契約を壊す変更を意図して行う場合のみ、このテストを更新すること。
    パッケージの ``__version__`` とは別物である。
    """
    assert api.PLUGIN_API_VERSION == 1


def test_package_version_is_a_separate_number() -> None:
    assert api.__version__ == metadata.version("vcenter-event-assistant-plugin-api")
    assert api.__version__ != str(api.PLUGIN_API_VERSION)


def test_everything_in_all_actually_exists() -> None:
    missing = [name for name in api.__all__ if not hasattr(api, name)]
    assert missing == []


def test_all_exports_the_type_aliases_authors_need() -> None:
    """従来 `ConnectionFactory` などは定義済みなのに未公開で、型注釈に使えなかった。"""
    for name in ("ConnectionFactory", "DataKind", "SeriesMode", "CollectionContext"):
        assert name in api.__all__
