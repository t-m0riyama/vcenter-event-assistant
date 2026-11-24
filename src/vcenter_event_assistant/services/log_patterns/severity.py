"""ログの重大度を取り込み・埋め戻しで共通の順位に揃える。"""

from vcenter_event_assistant.services.log_patterns.normalization import normalize_sql_text

WARNING_RANK = 2
_RANKS = {
    "critical": 4, "crit": 4, "fatal": 4, "panic": 4, "alert": 4, "emerg": 4,
    "error": 3, "err": 3,
    "warning": 2, "warn": 2,
    "info": 1, "notice": 1,
    "debug": 0, "verbose": 0, "trivia": 0,
}
WARNING_SEVERITIES = frozenset(word for word, rank in _RANKS.items() if rank >= WARNING_RANK)


def severity_rank(severity: str | None) -> int:
    return _RANKS.get(normalize_sql_text(severity or ""), 1)
