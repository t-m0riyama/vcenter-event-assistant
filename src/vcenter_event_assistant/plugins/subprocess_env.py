"""プラグイン関連の子プロセスに渡す環境変数。

ワーカーやインストーラは第三者のコード（プラグイン、sdist のビルドバックエンド）を実行する
ため、親の環境変数をそのまま引き継がず、許可したものだけを渡す（監査 M-1、Issue #235）。
``VEA_SECRET_KEY``・``DATABASE_URL``・LLM や SMTP の資格情報は渡さない。

子プロセスの Settings は ``.env`` も読まない（``VEA_SETTINGS_IGNORE_DOTENV``）。ワーカーが
必要とする設定は、``.env`` で指定されていても効くよう、親の Settings から値を取り出して渡す。
"""

from __future__ import annotations

import os

from vcenter_event_assistant.settings import Settings

#: 子プロセスの Settings に ``.env`` を読ませない印（``settings._settings_env_file``）。
IGNORE_DOTENV_ENV_VAR = "VEA_SETTINGS_IGNORE_DOTENV"

# OS・Python・TLS・プロキシなど、秘密を含まない実行環境の変数。
_RUNTIME_ENV_VARS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LANGUAGE",
        "TZ",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "NO_PROXY",
        "no_proxy",
    }
)
# プロキシの URL。資格情報（``http://user:pass@proxy``）を含むものは既定では渡さない。
PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_RUNTIME_ENV_PREFIXES = ("LC_",)

# インストーラ（uv）だけに渡す変数。インデックスの URL と資格情報（UV_INDEX_URL、
# UV_DEFAULT_INDEX、UV_INDEX_<名前>_PASSWORD など）は、sdist のビルドのコードから読めるので
# 渡さない。インデックスは ``VEA_PLUGIN_INDEX_URL`` で指定する。
_INSTALLER_ENV_VARS = frozenset(
    {
        "UV_CACHE_DIR",
        "UV_NO_CACHE",
        "UV_NATIVE_TLS",
        "UV_HTTP_TIMEOUT",
        "UV_CONCURRENT_DOWNLOADS",
        "UV_CONCURRENT_BUILDS",
        "UV_LINK_MODE",
        "UV_OFFLINE",
        "UV_NO_PROGRESS",
        "XDG_CACHE_HOME",
    }
)


def url_has_credentials(url: str | None) -> bool:
    """URL に資格情報（ユーザー情報）が含まれ得るか。

    ``@`` がどこかにあれば含むとみなす。``urlsplit`` はスキームのない ``user:pass@proxy:8080`` の
    ``user`` をスキームと解釈し、エンコードしていない ``/`` を含むパスワードではホストの位置も
    誤るので、解析結果には頼らない。パスの中の ``@`` も含むと判定するが、その誤りは安全側
    （wheel だけを入れる・プロキシを渡さない）に倒れる。
    """
    return bool(url) and "@" in url


def proxy_has_credentials() -> bool:
    """プロキシの環境変数のどれかが資格情報を含むか。"""
    return any(url_has_credentials(os.environ.get(name)) for name in PROXY_ENV_VARS)


def _runtime_env(*, with_proxy_credentials: bool = False) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name in _RUNTIME_ENV_VARS or name.startswith(_RUNTIME_ENV_PREFIXES)
    }
    for name in PROXY_ENV_VARS:
        value = os.environ.get(name)
        if value and (with_proxy_credentials or not url_has_credentials(value)):
            env[name] = value
    env[IGNORE_DOTENV_ENV_VAR] = "1"
    return env


def _passthrough_names(settings: Settings) -> list[str]:
    return [name.strip() for name in settings.plugin_worker_env_passthrough.split(",") if name.strip()]


def worker_env(settings: Settings) -> dict[str, str]:
    """コレクタワーカー（検出用を含む）に渡す環境変数。"""
    env = _runtime_env()
    # 資格情報付きのプロキシは、運用者が VEA_PLUGIN_WORKER_ENV_PASSTHROUGH に書いたときだけ渡す。
    # ワーカーが Settings で読む値（logging_config.configure_worker_logging と
    # collectors.connection.connect_vcenter）。
    env["LOG_LEVEL"] = settings.log_level
    if settings.collector_worker_log_level:
        env["VEA_COLLECTOR_WORKER_LOG_LEVEL"] = settings.collector_worker_log_level
    env["VCENTER_ALLOWED_HOST_SUFFIXES"] = settings.vcenter_allowed_host_suffixes
    for name in _passthrough_names(settings):
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def installer_env(*, with_credentials: bool = False) -> dict[str, str]:
    """プラグインのインストーラ（``uv pip install``）に渡す環境変数。

    資格情報付きのプロキシは ``with_credentials`` のときだけ渡す。sdist のビルドのコードから
    読めるので、呼び出し側はビルドしない（``--no-build``）ときだけ True にする。
    """
    env = _runtime_env(with_proxy_credentials=with_credentials)
    env.update({name: value for name, value in os.environ.items() if name in _INSTALLER_ENV_VARS})
    return env
