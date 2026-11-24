"""ログの重大度を取り込み・埋め戻し・集計で共通の順位に揃える。"""

from sqlalchemy import case
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.expression import SQLColumnExpression

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
_SEVERITY_NAMES = {0: "debug", 1: "info", 2: "warning", 3: "error", 4: "critical"}


def severity_rank(severity: str | None) -> int:
    return _RANKS.get(normalize_sql_text(severity or ""), 1)


def severity_name(rank: int) -> str:
    """重大度の順位を代表する語を返す。"""
    return _SEVERITY_NAMES.get(rank, "unknown")


def severity_rank_sql(normalized: SQLColumnExpression[str | None]) -> ColumnElement[int]:
    """揃えた重大度を、取り込みと同じ順位に変換する。"""
    return case(_RANKS, value=normalized, else_=1)
