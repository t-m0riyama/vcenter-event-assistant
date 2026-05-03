"""アラートレベル（ルール単位の重大度）の定数と表示ラベル。"""

from __future__ import annotations

from typing import Literal

# API / DB で使用する安定キー
AlertLevel = Literal["critical", "error", "warning"]

ALLOWED_ALERT_LEVELS: tuple[str, ...] = ("critical", "error", "warning")

# 日本語表示（メール・UI 共通で利用）
ALERT_LEVEL_LABEL_JA: dict[str, str] = {
    "critical": "クリティカル",
    "error": "エラー",
    "warning": "警告",
}


def alert_level_label_ja(level: str) -> str:
    """レベルキーに対応する日本語ラベルを返す。未知の値はそのまま返す。"""
    return ALERT_LEVEL_LABEL_JA.get(level, level)
