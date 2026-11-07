"""時刻列を DB 側でエポック秒・時間バケット番号に変換する式（SQLite / PostgreSQL 共通）。

式は呼び出しごとに新しいバインドパラメータを作る。PostgreSQL（asyncpg）では、同じ内容でも
別々に作った式は SELECT と GROUP BY で別のパラメータ番号になり、「must appear in the GROUP BY
clause」で失敗する。式は 1 回だけ作って使い回すか、副問い合わせの列にしてから GROUP BY すること。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, cast, func, literal
from sqlalchemy.sql.elements import ColumnElement


def truncate_to_second(dt: datetime) -> datetime:
    """UTC に揃え、秒未満を切り捨てる（naive は UTC とみなす）。

    DB 側のエポック秒は秒単位の切り捨てなので、期間の起点も秒に揃えておかないと、
    境界ちょうどのサンプルが Python 側の計算と別のバケットに入る。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def epoch_seconds_expr(column: Any, dialect_name: str) -> ColumnElement[int]:
    """``column`` の UTC エポック秒（秒未満は切り捨て、BIGINT）。"""
    if dialect_name == "postgresql":
        return cast(func.floor(func.extract("epoch", column)), BigInteger)
    # SQLite は日時を ``YYYY-MM-DD HH:MM:SS.ffffff`` の文字列で保存する。``strftime('%s')`` は
    # バージョンによって秒未満を丸めるので、秒までを切り出してから変換する。
    return cast(func.strftime("%s", func.substr(column, 1, 19)), BigInteger)


def bucket_index_expr(
    column: Any,
    dialect_name: str,
    *,
    from_epoch: int,
    bucket_sec: int,
) -> ColumnElement[int]:
    """``from_epoch`` を起点とした ``bucket_sec`` 幅のバケット番号（0 始まりの整数）。

    ``column >= from`` に絞り込んだ行に使う前提（負の値は扱わない）。
    """
    if bucket_sec < 1:
        raise ValueError("bucket_sec must be >= 1")
    epoch = epoch_seconds_expr(column, dialect_name)
    offset = epoch - literal(int(from_epoch), BigInteger)
    return offset // literal(int(bucket_sec), BigInteger)
