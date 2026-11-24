"""ログの種類と重大度を SQL と同じ形に揃える。"""

from string import ascii_lowercase, ascii_uppercase

_ASCII_LOWER = str.maketrans(ascii_uppercase, ascii_lowercase)


def normalize_sql_text(value: str) -> str:
    """SQLite の lower(trim(x)) と PostgreSQL の C 照合順序に揃える。"""
    return value.strip(" ").translate(_ASCII_LOWER)
