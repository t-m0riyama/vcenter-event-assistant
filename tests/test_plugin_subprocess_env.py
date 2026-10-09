"""プラグインの子プロセスに渡す環境変数（監査 M-1、Issue #235）。"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from vcenter_event_assistant.plugins.installer import _install_command
from vcenter_event_assistant.plugins.subprocess_env import installer_env, worker_env
from vcenter_event_assistant.settings import Settings

SECRETS = {
    "VEA_SECRET_KEY": "secret-key",
    "DATABASE_URL": "postgresql+asyncpg://vea:db-password@db/vea",
    "SMTP_PASSWORD": "smtp-password",
    "LLM_CHAT_API_KEY": "llm-key",
    "LANGSMITH_API_KEY": "langsmith-key",
    "TAVILY_API_KEY": "tavily-key",
    "VEA_BOOTSTRAP_ADMIN_PASSWORD": "bootstrap-password",
    "BOOTSTRAP_ADMIN_PASSWORD": "bootstrap-password-2",
    "UNRELATED_VARIABLE": "unrelated",
}


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)


def _settings(**values) -> Settings:
    return Settings(database_url="sqlite+aiosqlite:///:memory:", **values)


def _worker(settings: Settings) -> dict[str, str]:
    return worker_env(settings)


def _installer(settings: Settings) -> dict[str, str]:
    return installer_env()


@pytest.mark.usefixtures("secret_env")
@pytest.mark.parametrize("build", [_worker, _installer])
def test_secrets_are_not_passed(build) -> None:
    env = build(_settings())
    for name, value in SECRETS.items():
        assert name not in env
        assert value not in env.values()


@pytest.mark.parametrize("build", [_worker, _installer])
def test_runtime_environment_is_passed(monkeypatch: pytest.MonkeyPatch, build) -> None:
    passed = {
        "PATH": "/usr/bin",
        "HOME": "/home/app",
        "LANG": "ja_JP.UTF-8",
        "LC_ALL": "ja_JP.UTF-8",
        "TZ": "Asia/Tokyo",
        "TMPDIR": "/tmp/app",
        "SSL_CERT_FILE": "/etc/ssl/ca.pem",
        "HTTPS_PROXY": "http://proxy:8080",
        "no_proxy": "localhost",
    }
    for name, value in passed.items():
        monkeypatch.setenv(name, value)
    env = build(_settings())
    for name, value in passed.items():
        assert env[name] == value


@pytest.mark.parametrize("build", [_worker, _installer])
def test_children_do_not_read_dotenv(build) -> None:
    assert build(_settings())["VEA_SETTINGS_IGNORE_DOTENV"] == "1"


def test_worker_receives_its_settings_even_when_they_come_from_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # .env の値は os.environ に入らないので、親の Settings から取り出して渡す。
    for name in ("LOG_LEVEL", "VEA_COLLECTOR_WORKER_LOG_LEVEL", "VCENTER_ALLOWED_HOST_SUFFIXES"):
        monkeypatch.delenv(name, raising=False)
    parent = _settings(
        log_level="WARNING",
        collector_worker_log_level="DEBUG",
        vcenter_allowed_host_suffixes=".corp.local,.lab.local",
    )
    env = worker_env(parent)

    for name in list(SECRETS):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    child = Settings()
    assert child.log_level == "WARNING"
    assert child.collector_worker_log_level == "DEBUG"
    assert child.vcenter_allowed_host_suffix_list == parent.vcenter_allowed_host_suffix_list


def test_worker_omits_unset_worker_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VEA_COLLECTOR_WORKER_LOG_LEVEL", raising=False)
    assert "VEA_COLLECTOR_WORKER_LOG_LEVEL" not in worker_env(_settings())


@pytest.mark.usefixtures("secret_env")
def test_worker_passes_variables_the_operator_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_PLUGIN_TOKEN", "plugin-token")
    monkeypatch.delenv("MY_PLUGIN_MISSING", raising=False)
    env = worker_env(_settings(plugin_worker_env_passthrough=" MY_PLUGIN_TOKEN, MY_PLUGIN_MISSING ,"))
    assert env["MY_PLUGIN_TOKEN"] == "plugin-token"
    assert "MY_PLUGIN_MISSING" not in env
    assert "UNRELATED_VARIABLE" not in env


def test_installer_passes_only_credential_free_uv_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    kept = {"UV_CACHE_DIR": "/cache/uv", "UV_NATIVE_TLS": "1", "UV_HTTP_TIMEOUT": "60"}
    dropped = {
        "UV_INDEX_URL": "https://user:pass@mirror.example/simple",
        "UV_DEFAULT_INDEX": "https://user:pass@mirror.example/simple",
        "UV_EXTRA_INDEX_URL": "https://user:pass@mirror.example/simple",
        "UV_INDEX": "corp=https://user:pass@mirror.example/simple",
        "UV_INDEX_CORP_USERNAME": "user",
        "UV_INDEX_CORP_PASSWORD": "pass",
        "PIP_INDEX_URL": "https://user:pass@mirror.example/simple",
        "PIP_EXTRA_INDEX_URL": "https://user:pass@mirror.example/simple",
    }
    for name, value in {**kept, **dropped}.items():
        monkeypatch.setenv(name, value)
    env = installer_env()
    for name, value in kept.items():
        assert env[name] == value
    for name in dropped:
        assert name not in env
    # ワーカーには uv の変数も渡さない。
    assert "UV_CACHE_DIR" not in worker_env(_settings())


@pytest.mark.parametrize(
    ("index_url", "expect_no_build"),
    [
        ("https://user:pass@mirror.example/simple", True),
        ("https://token@mirror.example/simple", True),
        ("https://mirror.example/simple", False),
        (None, False),
    ],
)
def test_index_install_does_not_build_with_index_credentials(
    tmp_path, index_url: str | None, expect_no_build: bool
) -> None:
    # sdist のビルドバックエンドは uv のコマンドライン（/proc/<pid>/cmdline）を読めるため。
    settings = _settings(plugin_allow_index_install=True, plugin_index_url=index_url, uv_bin="/usr/bin/uv")
    command = _install_command(settings, tmp_path, "example-collector==1.0", from_index=True)
    assert ("--no-build" in command) is expect_no_build


def test_upload_with_index_allowed_uses_the_configured_index(tmp_path) -> None:
    # 依存の解決も、設定したインデックス（社内ミラー）から行う。
    settings = _settings(
        plugin_allow_index_install=True,
        plugin_index_url="https://user:pass@mirror.example/simple",
        uv_bin="/usr/bin/uv",
    )
    command = _install_command(settings, tmp_path, str(tmp_path / "pkg.whl"), from_index=False)
    assert command[command.index("--index-url") + 1] == "https://user:pass@mirror.example/simple"
    assert "--no-build" in command


def test_offline_upload_is_unchanged(tmp_path) -> None:
    settings = _settings(plugin_index_url="https://user:pass@mirror.example/simple", uv_bin="/usr/bin/uv")
    command = _install_command(settings, tmp_path, str(tmp_path / "pkg.tar.gz"), from_index=False)
    assert "--no-index" in command
    assert "--no-deps" in command
    assert "--index-url" not in command
    assert "--no-build" not in command


def test_settings_skip_dotenv_with_the_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    from vcenter_event_assistant.settings import _settings_env_file

    monkeypatch.delenv("VEA_PYTEST", raising=False)
    monkeypatch.delenv("VEA_SETTINGS_IGNORE_DOTENV", raising=False)
    assert _settings_env_file() == ".env"
    monkeypatch.setenv("VEA_SETTINGS_IGNORE_DOTENV", "1")
    assert _settings_env_file() is None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="prctl(PR_SET_DUMPABLE) is Linux only")
@pytest.mark.parametrize(("enabled", "readable"), [(True, False), (False, True)])
def test_children_cannot_read_the_parent_environment(enabled: bool, readable: bool) -> None:
    # 親（アプリ本体の代わり）を別プロセスで起動し、同じ UID の子から /proc/<親>/environ を読ませる。
    parent = textwrap.dedent(
        f"""
        import subprocess, sys
        from vcenter_event_assistant.process_hardening import harden_process
        from vcenter_event_assistant.settings import Settings
        harden_process(Settings(database_url="sqlite+aiosqlite:///:memory:", process_non_dumpable={enabled!r}))
        child = (
            "import os\\n"
            "try:\\n"
            "    open(f'/proc/{{os.getppid()}}/environ', 'rb').read()\\n"
            "    print('readable')\\n"
            "except PermissionError:\\n"
            "    print('denied')\\n"
        )
        print(subprocess.run([sys.executable, "-c", child], capture_output=True, text=True).stdout.strip())
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", parent],
        capture_output=True,
        text=True,
        env={**os.environ, "VEA_SECRET_KEY": "parent-secret"},
        check=True,
    )
    assert completed.stdout.strip() == ("readable" if readable else "denied")


def test_harden_process_is_a_no_op_off_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    from vcenter_event_assistant import process_hardening

    monkeypatch.setattr(process_hardening.sys, "platform", "darwin")
    assert process_hardening.harden_process(_settings()) is False


def test_sdist_upload_does_not_use_a_credentialed_index(tmp_path) -> None:
    # sdist はビルドが要るので --no-build は付けられない。資格情報を渡さないよう、
    # インデックスを使わないオフラインの経路で入れる（PR #273 の Codex レビューの指摘）。
    settings = _settings(
        plugin_allow_index_install=True,
        plugin_index_url="https://user:pass@mirror.example/simple",
        uv_bin="/usr/bin/uv",
    )
    command = _install_command(settings, tmp_path, str(tmp_path / "pkg-0.1.0.tar.gz"), from_index=False)
    assert "--index-url" not in command
    assert "--no-build" not in command
    assert "--no-index" in command
    assert "--no-deps" in command
    assert not any("pass@" in part for part in command)


def test_sdist_upload_uses_an_index_without_credentials(tmp_path) -> None:
    settings = _settings(
        plugin_allow_index_install=True,
        plugin_index_url="https://mirror.example/simple",
        uv_bin="/usr/bin/uv",
    )
    command = _install_command(settings, tmp_path, str(tmp_path / "pkg-0.1.0.tar.gz"), from_index=False)
    assert command[command.index("--index-url") + 1] == "https://mirror.example/simple"
    assert "--no-build" not in command
    assert "--no-index" not in command


_PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture
def no_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROXY_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("no_proxy_env")
@pytest.mark.parametrize("name", _PROXY_NAMES)
def test_credentialed_proxy_is_not_passed(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    # PR #273 の Codex レビューの指摘。プロキシの資格情報もプラグインに渡さない。
    monkeypatch.setenv(name, "http://user:proxy-secret@proxy:8080")
    assert name not in worker_env(_settings())
    assert name not in installer_env()
    assert installer_env(with_credentials=True)[name] == "http://user:proxy-secret@proxy:8080"


@pytest.mark.usefixtures("no_proxy_env")
def test_credentialed_proxy_can_be_passed_to_workers_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://user:proxy-secret@proxy:8080")
    env = worker_env(_settings(plugin_worker_env_passthrough="HTTPS_PROXY"))
    assert env["HTTPS_PROXY"] == "http://user:proxy-secret@proxy:8080"


@pytest.mark.usefixtures("no_proxy_env")
def test_credentialed_proxy_installs_wheels_only(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("https_proxy", "http://user:proxy-secret@proxy:8080")
    settings = _settings(
        plugin_allow_index_install=True,
        plugin_index_url="https://mirror.example/simple",
        uv_bin="/usr/bin/uv",
    )
    index_install = _install_command(settings, tmp_path, "example-collector==1.0", from_index=True)
    assert "--no-build" in index_install
    sdist_upload = _install_command(settings, tmp_path, str(tmp_path / "pkg-0.1.0.tar.gz"), from_index=False)
    assert "--no-index" in sdist_upload
    assert "--no-build" not in sdist_upload


@pytest.mark.usefixtures("no_proxy_env")
@pytest.mark.parametrize(("extra", "expect_proxy"), [(["--no-build"], True), (["--no-index", "--no-deps"], False)])
async def test_installer_gets_proxy_credentials_only_without_builds(
    monkeypatch: pytest.MonkeyPatch, extra: list[str], expect_proxy: bool
) -> None:
    from vcenter_event_assistant.plugins import installer

    monkeypatch.setenv("HTTPS_PROXY", "http://user:proxy-secret@proxy:8080")
    captured: dict[str, dict[str, str]] = {}

    class _Process:
        returncode = 0

        async def communicate(self):
            return b"", None

    async def fake_exec(*args, env, **kwargs):
        captured["env"] = env
        return _Process()

    monkeypatch.setattr(installer.asyncio, "create_subprocess_exec", fake_exec)
    await installer._run_install(["uv", "pip", "install", *extra, "pkg"])
    assert ("HTTPS_PROXY" in captured["env"]) is expect_proxy


@pytest.mark.usefixtures("no_proxy_env")
def test_proxy_without_credentials_is_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:8080")
    assert worker_env(_settings())["HTTPS_PROXY"] == "http://proxy:8080"
    assert installer_env()["HTTPS_PROXY"] == "http://proxy:8080"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://user:pass@proxy:8080", True),
        ("http://token@proxy:8080", True),
        # スキームのない形は urlsplit が user をスキームと解釈する（PR #273 の Codex レビューの指摘）。
        ("user:pass@proxy:8080", True),
        ("user@proxy", True),
        ("//user:pass@proxy:8080", True),
        # エンコードしていない "/" を含むパスワード。ホストの後ろにパスがあっても見逃さない
        # （PR #273 の Codex レビューの指摘）。
        ("user:pa/ss@proxy:8080", True),
        ("http://user:pa/ss@proxy:8080", True),
        ("user:pa/ss@proxy:8080/", True),
        ("http://user:pa/ss@proxy:8080/path", True),
        ("http://proxy:8080", False),
        ("proxy:8080", False),
        ("https://mirror.example/simple/", False),
        # "@" がどこにあっても資格情報とみなす。誤判定は安全側（wheel だけ・プロキシを渡さない）に倒れる。
        ("https://mirror.example/simple/@scope/pkg", True),
        ("", False),
        (None, False),
    ],
)
def test_url_has_credentials(url: str | None, expected: bool) -> None:
    from vcenter_event_assistant.plugins.subprocess_env import url_has_credentials

    assert url_has_credentials(url) is expected


@pytest.mark.usefixtures("no_proxy_env")
def test_schemeless_credentialed_proxy_is_not_passed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HTTP_PROXY", "user:proxy-secret@proxy:8080")
    assert "HTTP_PROXY" not in worker_env(_settings())
    assert "HTTP_PROXY" not in installer_env()
    settings = _settings(plugin_allow_index_install=True, uv_bin="/usr/bin/uv")
    sdist_upload = _install_command(settings, tmp_path, str(tmp_path / "pkg-0.1.0.tar.gz"), from_index=False)
    assert "--no-index" in sdist_upload


def _fake_parent(tmp_path, *, uid: int, environ: bytes, pid: int = 4242):
    proc = tmp_path / "proc"
    (proc / str(pid)).mkdir(parents=True)
    (proc / str(pid) / "status").write_text(f"Name:\tuv\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n", encoding="utf-8")
    (proc / str(pid) / "environ").write_bytes(environ)
    return proc, pid


@pytest.mark.parametrize(
    ("same_uid", "environ", "expect_warning"),
    [
        (True, b"PATH=/usr/bin\0VEA_SECRET_KEY=k\0", True),
        (True, b"PATH=/usr/bin\0DATABASE_URL=postgresql://u:p@db/x\0", True),
        (True, b"PATH=/usr/bin\0SMTP_PASSWORD=p\0", True),
        (True, b"PATH=/usr/bin\0LLM_CHAT_API_KEY=k\0", True),
        # Settings は大文字と小文字を区別しないので、小文字の名前も秘密として扱う。
        (True, b"PATH=/usr/bin\0database_url=postgresql://u:p@db/x\0", True),
        (True, b"PATH=/usr/bin\0vea_bootstrap_admin_password=p\0", True),
        # 資格情報を含む URL の変数も秘密として扱う。含まなければ警告しない。
        (True, b"PATH=/usr/bin\0VEA_PLUGIN_INDEX_URL=https://u:p@pypi.example/simple\0", True),
        (True, b"PATH=/usr/bin\0https_proxy=http://u:p@proxy:8080\0", True),
        (True, b"PATH=/usr/bin\0VCENTER_HTTP_PROXY=u:p@proxy:8080\0", True),
        (True, b"PATH=/usr/bin\0UV_INDEX_URL=https://u:p@pypi.example/simple\0", True),
        (True, b"PATH=/usr/bin\0HTTPS_PROXY=http://proxy:8080\0VEA_PLUGIN_INDEX_URL=https://pypi.example\0", False),
        (True, b"PATH=/usr/bin\0HOME=/home/app\0", False),
        (False, b"PATH=/usr/bin\0VEA_SECRET_KEY=k\0", False),
    ],
)
def test_warns_when_the_parent_keeps_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog, same_uid: bool, environ: bytes, expect_warning: bool
) -> None:
    # PR #273 の Codex レビューの指摘。uv run などの親が同じ UID で秘密の環境変数を持ったまま残ると、
    # ワーカーは /proc/<親>/environ を読める。
    from vcenter_event_assistant import process_hardening

    uid = 1000
    proc, pid = _fake_parent(tmp_path, uid=uid if same_uid else 0, environ=environ)
    monkeypatch.setattr(process_hardening.sys, "platform", "linux")
    monkeypatch.setattr(process_hardening.os, "getppid", lambda: pid)
    monkeypatch.setattr(process_hardening.os, "getuid", lambda: uid)
    with caplog.at_level("WARNING"):
        warned = process_hardening.warn_if_parent_keeps_secrets(proc_root=proc)
    assert warned is expect_warning
    # 対話シェルから exec を付けずに起動するとシェルが親として残るので、exec を明示して案内する。
    assert ("exec .venv/bin/vcenter-event-assistant" in caplog.text) is expect_warning
    # 同じユーザーのプロセス管理ツールは exec しても残るので、exec を解決策として示さない。
    assert "different user" in caplog.text or not expect_warning
    assert "process manager to exec" not in caplog.text
    # 値はログに出さない。
    assert "u:p@" not in caplog.text


def test_parent_check_ignores_unreadable_parents(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from vcenter_event_assistant import process_hardening

    monkeypatch.setattr(process_hardening.sys, "platform", "linux")
    monkeypatch.setattr(process_hardening.os, "getppid", lambda: 999999)
    assert process_hardening.warn_if_parent_keeps_secrets(proc_root=tmp_path / "proc") is False
    monkeypatch.setattr(process_hardening.sys, "platform", "darwin")
    assert process_hardening.warn_if_parent_keeps_secrets() is False
