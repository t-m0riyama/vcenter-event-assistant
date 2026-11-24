"""ログの種類と重大度を SQL と同じ形に揃える。"""

from string import ascii_lowercase, ascii_uppercase

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.expression import SQLColumnExpression

_ASCII_LOWER = str.maketrans(ascii_uppercase, ascii_lowercase)


def normalize_sql_text(value: str) -> str:
    """SQLite の lower(trim(x)) と PostgreSQL の C 照合順序に揃える。"""
    return value.strip(" ").translate(_ASCII_LOWER)


def normalized_text_sql(
    column: SQLColumnExpression[str | None], dialect_name: str,
) -> ColumnElement[str | None]:
    """PostgreSQL でも SQLite と同じ ASCII の小文字化を行う。"""
    trimmed = func.trim(column)
    return func.lower(trimmed.collate("C") if dialect_name == "postgresql" else trimmed)
