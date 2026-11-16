"""LIKE による部分一致の条件（SQLite / PostgreSQL 共通）。"""

from __future__ import annotations

from sqlalchemy import func, literal
from sqlalchemy.sql.elements import ColumnElement


def escape_like_metachars(s: str) -> str:
    """LIKE のワイルドカード（``%`` と ``_``）とエスケープ文字そのものを文字どおりに扱わせる。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains_case_insensitive(column: ColumnElement[str | None], needle: str) -> ColumnElement[bool]:
    """Substring match, case-insensitive; works on SQLite and PostgreSQL via ``ilike`` + escape."""
    hay = func.coalesce(column, literal(""))
    return hay.ilike(f"%{escape_like_metachars(needle)}%", escape="\\")
