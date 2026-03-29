"""アプリ・uvicorn 向け logging の dictConfig 構築。"""

from __future__ import annotations

import logging.config
import sys
from pathlib import Path
from typing import Any

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
