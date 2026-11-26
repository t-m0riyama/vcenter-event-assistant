"""収集の失敗として記録されうる文字列を、画面の案内の対応表と照らすための一覧に書き出す。

画面（``frontend/src/utils/collectionErrorMessage.ts``）は、バックエンドが記録する文字列の形
（例外の型名や、ワーカーの文言）を前提に案内を出す。バックエンドに失敗の型や文言が増えても、
画面は黙って一般の「収集できませんでした。」になる。この一覧を
``frontend/src/utils/collectionErrorRecords.json`` に置き、フロントのテスト
（``collectionErrorRecords.test.ts``）が、どれにも案内があることを確かめる。

画面の失敗の表示に届くのは、次の 3 つの列だけである。
- ``CollectorRunState.error_message``（``plugins/runtime.py`` の ``_mark_failed``。文言は ``_safe_error``）
- ``InventorySyncState.last_error`` と ``config_last_error``（``services/inventory.py`` の ``_record_failure``）

一覧が古いとこのテストが落ちる。直すには次を実行し、フロントの対応表も合わせる::

    UPDATE_COLLECTION_ERROR_RECORDS=1 uv run pytest tests/test_collection_error_records.py
"""

from __future__ import annotations

import ast
import json
import os
import socket
import ssl
from pathlib import Path

from pyVmomi import vim, vmodl
from vcenter_event_assistant_plugin_api.validation import BatchValidationError, Issue

from vcenter_event_assistant.collectors.connection import VCENTER_HTTPS_REQUIRED
from vcenter_event_assistant.plugins import runtime
from vcenter_event_assistant.plugins.remote import CollectorWorkerError
from vcenter_event_assistant.plugins.runtime import _safe_error
from vcenter_event_assistant.services.inventory import _READ_ERRORS
from vcenter_event_assistant.services.ssh_management import LegacySSHPathError, ssh_objects

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "frontend" / "src" / "utils" / "collectionErrorRecords.json"
PLUGINS = ROOT / "src" / "vcenter_event_assistant" / "plugins"
WORKER = PLUGINS / "worker.py"

# プラグインの発見（一覧の取得）の失敗。``registration.error`` や API の 503 になり、
# 収集の失敗の列には記録されない。
_DISCOVERY_ONLY = frozenset({
    "discovery failed",
    "plugin discovery did not return a complete response",
    "plugin discovery produced no response",
    "plugin discovery session unavailable",
    "plugin discovery timed out",
    "plugin worker discovery is unavailable",
    "plugin worker discovery service is unavailable",
})

# 収集で起こりうる代表の例外。_safe_error を通した形で一覧に入れる。
_REPRESENTATIVE_ERRORS: tuple[BaseException, ...] = (
    vim.fault.InvalidLogin(),
    vim.fault.NoPermission(),
    vim.fault.NotAuthenticated(),
    vmodl.fault.SecurityError(),
    vmodl.fault.HostCommunication(),
    vmodl.fault.ManagedObjectNotFound(),
    vmodl.query.InvalidProperty(),
    ssl.SSLCertVerificationError(),
    socket.gaierror(),
    ConnectionRefusedError(),
    ConnectionResetError(),
    TimeoutError(),
    OSError(),
    ValueError("x"),
    AttributeError("x"),
    TypeError("x"),
    KeyError("x"),
    RuntimeError("x"),
    Exception("x"),
)


def _worker_error_names() -> set[str]:
    names, pending = set(), [CollectorWorkerError]
    while pending:
        cls = pending.pop()
        names.add(cls.__name__)
        pending.extend(cls.__subclasses__())
    return names


def _string_default(node: ast.AST) -> str | None:
    """``str(x.get(key, "既定"))`` の形なら、既定の文言を返す。"""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str" and node.args:
        inner = node.args[0]
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and inner.func.attr == "get"
            and len(inner.args) == 2
            and isinstance(inner.args[1], ast.Constant)
            and isinstance(inner.args[1].value, str)
        ):
            return inner.args[1].value
    return None


def _worker_messages() -> list[str]:
    """``plugins/`` でワーカーの失敗に渡す文言（記録の型名の位置に残る）を拾う。

    知らない形の第 1 引数（f-string や変数）や位置引数の無い呼び出しを見つけたら落とす。拾えない文言を
    黙って見逃さないため。走査は ``plugins/`` に限る。ワーカーとの通信（``remote.py``）とその失敗の型は
    ここにあり、``services/`` などの収集の経路はワーカーの失敗を投げずに、ふつうの例外を投げるため
    （それは代表の例外の一覧で照らす）。
    """
    names = _worker_error_names()
    messages: set[str] = set()
    unknown: list[str] = []
    for path in sorted(PLUGINS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if called not in names:
                continue
            if not node.args:
                unknown.append(f"{path.relative_to(ROOT)}:{node.lineno}（位置引数が無い）")
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                messages.add(first.value)
            elif (default := _string_default(first)) is not None:
                messages.add(default)
            else:
                unknown.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert unknown == [], f"拾えない形でワーカーの失敗を作っている: {unknown}"
    return sorted(messages)


def _worker_reported_types() -> list[str]:
    """``worker.py`` が型名の代わりに固定の文言を返す箇所（``"error": "ResponseTooLarge"`` など）。"""
    found: set[str] = set()
    for node in ast.walk(ast.parse(WORKER.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "error"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    found.add(value.value)
    return sorted(found)


def _example(cls: type[BaseException]) -> BaseException:
    """中身をそのまま載せてよい型の例。``BatchValidationError`` は問題の一覧から作る。"""
    if issubclass(cls, BatchValidationError):
        return cls((Issue(code="example", message="バッチの検証に失敗しました"),))
    return cls("detail")


def _legacy_ssh_path_error() -> LegacySSHPathError:
    """分離モードで SSH の鍵のファイルを直接指定したときの、本物の例外（文言を仮の文にしない）。"""
    legacy = {"host": "h", "username": "u", "private_key_file": "k", "known_hosts_file": "kh"}
    try:
        list(ssh_objects(legacy, {"x-vea-ssh-connection": "ssh_connection_id"}, allow_legacy=False))
    except LegacySSHPathError as exc:
        return exc
    raise AssertionError("LegacySSHPathError を起こせない（ssh_objects の条件が変わった）")


def _records() -> dict[str, list[str]]:
    worker = [m for m in _worker_messages() if m not in _DISCOVERY_ONLY] + _worker_reported_types()
    return {
        # services/inventory.py の _record_failure と同じ形（型名: 日本語の説明）。
        "inventory_reads": [f"{kind.__name__}: {detail}" for kind, detail in _READ_ERRORS.items()],
        # plugins/runtime.py の _safe_error がワーカーの失敗を記録する形。
        "worker": [_safe_error(CollectorWorkerError(message)) for message in sorted(set(worker))],
        # 中身をそのまま載せてよい型（_SAFE_DETAIL_TYPES）。
        "safe_detail": [_safe_error(_example(cls)) for cls in runtime._SAFE_DETAIL_TYPES],
        "representative": [_safe_error(exc) for exc in _REPRESENTATIVE_ERRORS],
        # 型名なしの日本語の文言。画面はそのまま出す。
        "japanese": [VCENTER_HTTPS_REQUIRED, _safe_error(_legacy_ssh_path_error())],
    }


def _render(records: dict[str, list[str]]) -> str:
    return json.dumps(records, ensure_ascii=False, indent=2) + "\n"


def test_worker_messages_are_found() -> None:
    """拾い方が壊れて一覧が欠けると、照合が何も確かめなくなる。"""
    messages = set(_worker_messages())
    assert {"worker exited before responding", "plugin worker service is unavailable", "unknown error"} <= messages
    # 発見だけの文言の一覧が古くなっていない（消えた文言を除外し続けない）。
    assert _DISCOVERY_ONLY <= messages
    assert "ResponseTooLarge" in _worker_reported_types()


def test_collection_error_records_are_current() -> None:
    expected = _render(_records())
    if os.environ.get("UPDATE_COLLECTION_ERROR_RECORDS") == "1":
        RECORDS.write_text(expected, encoding="utf-8")
    assert RECORDS.read_text(encoding="utf-8") == expected, (
        "収集の失敗の一覧が古い。UPDATE_COLLECTION_ERROR_RECORDS=1 uv run pytest "
        "tests/test_collection_error_records.py で書き直し、collectionErrorMessage.ts の対応表も合わせる。"
    )
