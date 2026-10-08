"""アプリ・uvicorn 向け logging の dictConfig 構築。"""

from __future__ import annotations

import logging.config
import sys
from pathlib import Path
from typing import Any

from vcenter_event_assistant_plugin_api.logs import (
    PLUGIN_LOGGER_NAMESPACE as _PLUGIN_LOGGER_NAMESPACE,
)

from vcenter_event_assistant.settings import Settings

_LOG_FORMAT_CONSOLE = "%(levelname)s [%(name)s] %(message)s"
_LOG_FORMAT_FILE = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_ROTATE_BYTES = 10 * 1024 * 1024
_ROTATE_BACKUP = 5


def _ensure_parent_dir(path: str) -> None:
    """ログファイルの親ディレクトリを作成する（存在すれば何もしない）。"""
    parent = Path(path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


def build_logging_dict(settings: Settings) -> dict[str, Any]:
    """
    `logging.config.dictConfig` 用の辞書を組み立てる。

    - `vcenter_event_assistant`: アプリ本体
    - `uvicorn` / `uvicorn.error` / `uvicorn.access`: サーバ・アクセスログ
    """
    level = settings.log_level
    handlers: dict[str, Any] = {
        "console": {
            "class": "logging.StreamHandler",
            "level": "NOTSET",
            "formatter": "console",
            "stream": sys.stderr,
        },
    }
    # アプリ配下は root へ伝播させる（pytest caplog が root にハンドラを付けるため）。
    # コンソール出力は root のみとし、ここではファイル用ハンドラだけを付ける。
    loggers: dict[str, Any] = {
        "vcenter_event_assistant": {
            "handlers": [],
            "level": level,
            "propagate": True,
        },
        "uvicorn": {
            "handlers": ["console"],
            "level": level,
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["console"],
            "level": level,
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["console"],
            "level": level,
            "propagate": False,
        },
    }

    if settings.app_log_file:
        _ensure_parent_dir(settings.app_log_file)
        handlers["app_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "NOTSET",
            "formatter": "file",
            "filename": settings.app_log_file,
            "maxBytes": _ROTATE_BYTES,
            "backupCount": _ROTATE_BACKUP,
            "encoding": "utf-8",
        }
        loggers["vcenter_event_assistant"]["handlers"] = ["app_file"]

    if settings.uvicorn_log_file:
        _ensure_parent_dir(settings.uvicorn_log_file)
        handlers["uvicorn_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "NOTSET",
            "formatter": "file",
            "filename": settings.uvicorn_log_file,
            "maxBytes": _ROTATE_BYTES,
            "backupCount": _ROTATE_BACKUP,
            "encoding": "utf-8",
        }
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            loggers[name]["handlers"].append("uvicorn_file")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {
                "format": _LOG_FORMAT_CONSOLE,
            },
            "file": {
                "format": _LOG_FORMAT_FILE,
                "datefmt": _DATE_FMT,
            },
        },
        "handlers": handlers,
        "loggers": loggers,
        "root": {
            "handlers": ["console"],
            "level": level,
        },
    }


def configure_logging(settings: Settings) -> None:
    """logging を上書き設定する（uvicorn 既定と衝突するため `force=True`）。"""
    logging.config.dictConfig(build_logging_dict(settings))


#: 外部プラグインが使うロガーの名前空間。
#:
#: 定義は plugin-api 側（``logs.PLUGIN_LOGGER_NAMESPACE``）にある。プラグインは
#: ``get_plugin_logger()`` でこの配下のロガーを取り、ワーカーはこの配下だけレベルを
#: 切り替える。両者が同じ定数を見ていなければ機能しないので、再公開で一元化する。
PLUGIN_LOGGER_NAMESPACE = _PLUGIN_LOGGER_NAMESPACE

_LOG_FORMAT_WORKER = "%(levelname)s [collector-worker %(process)d] [%(name)s] %(message)s"


def build_worker_logging_dict(settings: Settings, *, stream: Any) -> dict[str, Any]:
    """コレクタワーカープロセス用の dictConfig を組み立てる。

    アプリ本体の設定とは意図的に別物である。

    - ハンドラは ``stream`` への `StreamHandler` 1 本だけにする。ワーカーで
      `RotatingFileHandler` を開くと、親と子が同一ファイルをローテートして
      リネームが競合し、親のログが失われる。ログの永続化は親のプロセス管理
      （systemd / docker logs 等）に委ねる。
    - ``stream`` は呼び出し側が明示的に渡す。ワーカーの stdout は JSON Lines
      プロトコル専用であり、そこへ 1 バイトでも書くと通信が壊れるため、
      ここで `sys.stdout` を参照してはならない。
    """
    level = settings.log_level
    plugin_level = settings.collector_worker_log_level or level
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"worker": {"format": _LOG_FORMAT_WORKER}},
        "handlers": {
            "stream": {
                "class": "logging.StreamHandler",
                "level": "NOTSET",
                "formatter": "worker",
                "stream": stream,
            },
        },
        "loggers": {
            # 外部プラグインだけをアプリ全体とは別のレベルで扱えるようにする。
            PLUGIN_LOGGER_NAMESPACE: {
                "handlers": [],
                "level": plugin_level,
                "propagate": True,
            },
        },
        "root": {"handlers": ["stream"], "level": level},
    }


def configure_worker_logging(settings: Settings, *, stream: Any) -> None:
    """コレクタワーカープロセスの logging を設定する。

    ワーカーは従来これを一切行っておらず、プラグインの ``logger.info()`` は
    ハンドラもレベルも持たないまま捨てられていた。
    """
    logging.config.dictConfig(build_worker_logging_dict(settings, stream=stream))
