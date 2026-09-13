"""コレクタワーカーの可観測性。

ワーカーは長らく logging を一切設定しておらず、プラグインの ``logger.info()`` は
ハンドラもレベルも持たないまま捨てられていた。ここでは

1. ワーカー用の dictConfig が stderr だけを使い、ファイルハンドラを開かないこと
2. プラグインのログが実際にワーカーの stderr へ出ること
3. その間も stdout が JSON Lines プロトコル専用のまま保たれること
4. 例外メッセージが allow-list に載る型に限って親へ渡ること

を固定する。3 は破ると全機能が止まるため、安い保険として外せない。
"""

from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
import textwrap
import uuid

import pytest

from vcenter_event_assistant.logging_config import (
    PLUGIN_LOGGER_NAMESPACE,
    build_worker_logging_dict,
    configure_worker_logging,
)
from vcenter_event_assistant.plugins.remote import (
    CollectorWorkerError,
    build_remote_plugins,
)
from vcenter_event_assistant.plugins.runtime import _safe_error
from vcenter_event_assistant.settings import Settings

WORKER_TIMEOUT = 60

_LOGGING_PLUGIN_BODY = '''
import logging
from datetime import datetime, timezone

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectorManifest,
    MetricDefinition,
    MetricSampleInput,
)

logger = logging.getLogger(
    "vcenter_event_assistant.plugins.external.example.logging"
)


class Collector:
    manifest = CollectorManifest(
        "example.logging",
        "Example Logging",
        "0.1.0",
        data_kinds=frozenset({"metric"}),
        metric_definitions=(
            MetricDefinition("example.logging.value", "Value", "n", "HostSystem"),
        ),
    )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def collect(self, context) -> CollectionBatch:
        logger.info("plugin-info-marker sensor=%s", context.config.get("sensor"))
        logger.debug("plugin-debug-marker")
        return CollectionBatch(
            metrics=(
                MetricSampleInput(
                    datetime.now(timezone.utc),
                    "HostSystem",
                    "host-1",
                    "esxi-01",
                    "example.logging.value",
                    1.0,
                ),
            )
        )


def build_collector():
    return Collector()
'''

# import そのものが失敗する配布物。オフライン（--no-deps）導入で最も多い失敗形。
_MISSING_DEPENDENCY_BODY = """
import totally_absent_dependency  # noqa: F401


def build_collector():
    raise AssertionError("unreachable")
"""

# KeyError のメッセージは「見つからなかったキー」そのもの。allow-list の境界確認用。
_KEYERROR_PLUGIN_BODY = '''
from vcenter_event_assistant_plugin_api import CollectorManifest, MetricDefinition


class Collector:
    manifest = CollectorManifest(
        "example.keyerror",
        "Example KeyError",
        "0.1.0",
        data_kinds=frozenset({"metric"}),
        metric_definitions=(
            MetricDefinition("example.keyerror.value", "Value", "n", "HostSystem"),
        ),
    )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def collect(self, context):
        # 秘密の値でルックアップして失敗する、という筋の悪いが起こりうるコード。
        {}["do-not-leak-secret-key"]


def build_collector():
    return Collector()
'''


def _install(root, module_body: str, *, entry_point: str, distribution: str):
    """``<root>/<distribution>/0.1.0/`` に import 可能な配布物を書き出す。"""
    target = root / distribution / "0.1.0"
    target.mkdir(parents=True)
    module = distribution.replace("-", "_")
    (target / f"{module}.py").write_text(module_body, encoding="utf-8")

    dist_info = target / f"{module}-0.1.0.dist-info"
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
    (dist_info / "entry_points.txt").write_text(
        "[vcenter_event_assistant.collectors]\n"
        f"{entry_point} = {module}:build_collector\n",
        encoding="utf-8",
    )
    (dist_info / "RECORD").write_text("", encoding="utf-8")
    return target


def _run_worker(plugin_path: str, requests: list[dict], *, env_extra=None):
    """ワーカーを 1 回起動し、要求を流して (stdout, stderr) を返す。

    ``build_remote_plugins`` は ``stderr=None``（親へ継承）なので stderr を掴めない。
    ここだけは直接 subprocess を起こして両方を捕まえる。
    """
    import os

    env = dict(os.environ)
    env.setdefault("MOCK_MODE", "true")
    if env_extra:
        env.update(env_extra)
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "vcenter_event_assistant.plugins.worker",
            "--plugin-path",
            plugin_path,
        ],
        input=payload,
        capture_output=True,
        text=True,
        timeout=WORKER_TIMEOUT,
        env=env,
    )
    return completed


def _collect_request(entry_point: str, request_id: int = 2) -> dict:
    return {
        "id": request_id,
        "op": "collect",
        "entry_point": entry_point,
        "context": {
            "target": {
                "id": str(uuid.uuid4()),
                "name": "Alpha",
                "host": "vc.example.com",
                "protocol": "https",
                "port": 443,
                "username": "user",
                "verify_ssl": True,
            },
            "config": {"sensor": "system-board"},
            "previous_cursor": None,
            "mock_mode": True,
        },
        "connection": {
            "host": "vc.example.com",
            "protocol": "https",
            "port": 443,
            "username": "user",
            "password": "do-not-leak-secret-value",
            "verify_ssl": True,
            "proxy_url": None,
            "ca_bundle_path": None,
        },
    }


# --- dictConfig の形 -------------------------------------------------------


def test_worker_logging_uses_the_given_stream_only() -> None:
    stream = io.StringIO()
    config = build_worker_logging_dict(Settings(), stream=stream)

    assert list(config["handlers"]) == ["stream"]
    assert config["handlers"]["stream"]["stream"] is stream
    assert config["root"]["handlers"] == ["stream"]


def test_worker_logging_never_opens_a_rotating_file_handler(tmp_path) -> None:
    """親と子が同じファイルをローテートすると親のログが失われるため。"""
    settings = Settings(app_log_file=str(tmp_path / "app.log"))
    config = build_worker_logging_dict(settings, stream=io.StringIO())

    classes = {h["class"] for h in config["handlers"].values()}
    assert classes == {"logging.StreamHandler"}
    assert not (tmp_path / "app.log").exists()


def test_worker_log_level_defaults_to_log_level() -> None:
    config = build_worker_logging_dict(Settings(log_level="WARNING"), stream=io.StringIO())

    assert config["root"]["level"] == "WARNING"
    assert config["loggers"][PLUGIN_LOGGER_NAMESPACE]["level"] == "WARNING"


def test_plugin_namespace_level_can_be_raised_on_its_own() -> None:
    """アプリ全体を DEBUG にせず外部プラグインだけ DEBUG にできる。"""
    settings = Settings(log_level="INFO", collector_worker_log_level="DEBUG")
    config = build_worker_logging_dict(settings, stream=io.StringIO())

    assert config["root"]["level"] == "INFO"
    assert config["loggers"][PLUGIN_LOGGER_NAMESPACE]["level"] == "DEBUG"


@pytest.fixture
def restore_logging():
    """`dictConfig` はグローバルな root ロガーを書き換えるため、必ず巻き戻す。

    巻き戻さないと後続テストの caplog（root にハンドラを付ける）が壊れる。
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_disabled = {
        name: logger.disabled
        for name, logger in logging.root.manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
    }
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        for name, disabled in saved_disabled.items():
            logger = logging.getLogger(name)
            logger.disabled = disabled


def test_configure_worker_logging_makes_plugin_logs_reach_the_stream(
    restore_logging,
) -> None:
    stream = io.StringIO()
    configure_worker_logging(Settings(log_level="INFO"), stream=stream)

    logging.getLogger(f"{PLUGIN_LOGGER_NAMESPACE}.example").info("marker-a")

    assert "marker-a" in stream.getvalue()


# --- 実プロセスでの挙動 ----------------------------------------------------


def test_plugin_logs_reach_stderr_and_stdout_stays_protocol_only(tmp_path) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    _install(
        root,
        _LOGGING_PLUGIN_BODY,
        entry_point="example.logging",
        distribution="example-logging",
    )
    target = str((root / "example-logging" / "0.1.0").resolve())

    completed = _run_worker(
        target,
        [
            {"id": 1, "op": "start", "entry_point": "example.logging"},
            _collect_request("example.logging"),
        ],
    )

    # 1. プラグインのログが stderr に出る（従来は消えていた）。
    assert "plugin-info-marker" in completed.stderr
    assert "collector-worker" in completed.stderr, completed.stderr

    # 2. stdout は JSON Lines だけ。1 行でも壊れていればプロトコルが死ぬ。
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines, completed.stderr
    responses = [json.loads(line) for line in lines]
    assert all(r["ok"] for r in responses), responses
    assert len(responses[-1]["result"]["batch"]["metrics"]) == 1

    # 3. 資格情報が stderr にも出ていない。
    assert "do-not-leak-secret-value" not in completed.stderr


def test_a_plugin_keyerror_does_not_leak_the_key_through_the_protocol(tmp_path) -> None:
    """``KeyError`` のメッセージは見つからなかったキー自身なので通してはならない。

    ``LookupError`` を allow-list に載せると ``KeyError`` まで通る。秘密の値で辞書を
    引いているプラグインでは、その値が管理画面に出てしまう。
    """
    root = tmp_path / "plugins"
    root.mkdir()
    _install(
        root,
        _KEYERROR_PLUGIN_BODY,
        entry_point="example.keyerror",
        distribution="example-keyerror",
    )
    target = str((root / "example-keyerror" / "0.1.0").resolve())

    completed = _run_worker(
        target, [_collect_request("example.keyerror", request_id=1)]
    )

    response = json.loads(
        [line for line in completed.stdout.splitlines() if line.strip()][-1]
    )
    assert response["ok"] is False
    assert response["error"] == "KeyError"
    # 型名だけ。detail は付かない。
    assert "detail" not in response
    assert "do-not-leak-secret-key" not in completed.stdout


def test_unknown_entry_point_still_names_itself(tmp_path) -> None:
    """専用型に絞っても、ワーカー自身のメッセージは通り続ける。"""
    root = tmp_path / "plugins"
    root.mkdir()
    _install(
        root,
        _LOGGING_PLUGIN_BODY,
        entry_point="example.logging",
        distribution="example-logging",
    )
    target = str((root / "example-logging" / "0.1.0").resolve())

    completed = _run_worker(
        target, [{"id": 1, "op": "start", "entry_point": "example.absent"}]
    )

    response = json.loads(
        [line for line in completed.stdout.splitlines() if line.strip()][-1]
    )
    assert response["ok"] is False
    assert response["error"] == "EntryPointNotFound"
    assert response["detail"] == "entry point not found: example.absent"


def test_debug_logs_are_dropped_unless_the_worker_level_allows_them(tmp_path) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    _install(
        root,
        _LOGGING_PLUGIN_BODY,
        entry_point="example.logging",
        distribution="example-logging",
    )
    target = str((root / "example-logging" / "0.1.0").resolve())
    requests = [
        {"id": 1, "op": "start", "entry_point": "example.logging"},
        _collect_request("example.logging"),
    ]

    default = _run_worker(target, requests)
    assert "plugin-debug-marker" not in default.stderr

    verbose = _run_worker(
        target, requests, env_extra={"VEA_COLLECTOR_WORKER_LOG_LEVEL": "DEBUG"}
    )
    assert "plugin-debug-marker" in verbose.stderr


def test_missing_dependency_names_the_module_in_the_failure_reason(tmp_path) -> None:
    """オフライン導入で最も多い失敗。従来は型名だけで原因が分からなかった。"""
    root = tmp_path / "plugins"
    root.mkdir()
    _install(
        root,
        _MISSING_DEPENDENCY_BODY,
        entry_point="example.broken",
        distribution="example-broken",
    )

    plugins, failures = build_remote_plugins(str(root))

    assert plugins == []
    reason = failures["example.broken"]
    assert "ModuleNotFoundError" in reason
    assert "totally_absent_dependency" in reason


def test_discovery_worker_stderr_is_transcribed_on_failure(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    """検出ワーカーは capture_output で起動するので、親が転記しないと消える。"""
    root = tmp_path / "plugins"
    root.mkdir()
    _install(
        root,
        _MISSING_DEPENDENCY_BODY,
        entry_point="example.broken",
        distribution="example-broken",
    )

    with caplog.at_level(logging.WARNING, logger="vcenter_event_assistant.plugins.remote"):
        build_remote_plugins(str(root))

    transcribed = "\n".join(
        record.getMessage()
        for record in caplog.records
        if "discovery worker output" in record.getMessage()
    )
    assert "totally_absent_dependency" in transcribed
    assert "Traceback" in transcribed


# --- allow-list の境界 -----------------------------------------------------


def test_safe_error_passes_worker_detail_through() -> None:
    exc = CollectorWorkerError(
        "ModuleNotFoundError", detail="No module named 'totally_absent_dependency'"
    )
    assert _safe_error(exc) == (
        "ModuleNotFoundError: No module named 'totally_absent_dependency'"
    )


def test_safe_error_keeps_the_plugin_exception_type_without_detail() -> None:
    """detail が無い型では、型名だけを見せて定型句に戻る。"""
    assert _safe_error(CollectorWorkerError("RuntimeError")) == (
        "RuntimeError: collector execution failed"
    )


def test_safe_error_hides_messages_of_types_outside_the_allow_list() -> None:
    exc = RuntimeError("do-not-leak-secret-value")
    assert _safe_error(exc) == "RuntimeError: collector execution failed"
    assert "do-not-leak" not in _safe_error(exc)


def test_safe_error_hides_keyerror_messages() -> None:
    """``KeyError`` のメッセージはキー自身なので、``LookupError`` ごと通してはならない。"""
    exc = KeyError("do-not-leak-secret-key")
    assert _safe_error(exc) == "KeyError: collector execution failed"
    assert "do-not-leak" not in _safe_error(exc)


def test_safe_error_shows_messages_of_allow_listed_types() -> None:
    exc = ModuleNotFoundError("No module named 'pyvmomi_extra'")
    assert _safe_error(exc) == (
        "ModuleNotFoundError: No module named 'pyvmomi_extra'"
    )


def test_safe_error_truncates_long_details() -> None:
    exc = CollectorWorkerError("ImportError", detail="x" * 5000)
    assert len(_safe_error(exc)) == 1000


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR"])
def test_collector_worker_log_level_accepts_valid_levels(level: str) -> None:
    assert Settings(collector_worker_log_level=level).collector_worker_log_level == level


def test_collector_worker_log_level_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        Settings(collector_worker_log_level="LOUD")


def test_blank_collector_worker_log_level_means_inherit() -> None:
    assert Settings(collector_worker_log_level="").collector_worker_log_level is None
