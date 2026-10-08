"""認証・認可の監査ログ（logger ``vcenter_event_assistant.audit``）。

パスワードやトークンは絶対に渡さないこと。
"""

from __future__ import annotations

import logging

audit_logger = logging.getLogger("vcenter_event_assistant.audit")


def _fmt(value: object) -> str:
    text = str(value)
    # ログインジェクション対策: 空白・引用符・制御文字（NUL、ESC による ANSI エスケープ等）を
    # 含む値は repr でエスケープして 1 行に収める
    if not text or any(c.isspace() or not c.isprintable() or c in "\"'" for c in text):
        return repr(text)
    return text


def audit(event: str, *, level: int = logging.INFO, **fields: object) -> None:
    parts = [f"event={event}"]
    parts.extend(f"{k}={_fmt(v)}" for k, v in fields.items() if v is not None)
    audit_logger.log(level, "AUDIT %s", " ".join(parts))
