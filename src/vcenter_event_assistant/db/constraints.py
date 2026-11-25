"""SQLite と PostgreSQL で制約違反を見分ける。"""

from sqlalchemy.exc import IntegrityError


def is_constraint(exc: IntegrityError, sqlstate: str, sqlite_code: int) -> bool:
    return (
        getattr(exc.orig, "sqlstate", None) == sqlstate
        or getattr(exc.orig, "sqlite_errorcode", None) == sqlite_code
    )
