"""SQLite で、FROM の表に ``INDEXED BY`` を付けて索引を固定する（Issue #334）。

SQLAlchemy の SQLite のコンパイラは ``get_from_hint_text`` が ``None`` を返すので、``Select.with_hint`` の
ヒントを出力しない。これを 1 回だけ差し替え、``INDEXED BY `` で始まるヒントだけを FROM の表の後ろに出す
（それ以外は今までどおり出さない。方言を指定しない ``with_hint`` も SQLite のコンパイラに届くため）。

ヒントは ``select`` ごとに付き、別名（``aliased``）の表や PostgreSQL には付かない。

ほかの方法を使わない理由:

- ``@compiles(Table, "sqlite")``: FROM 以外（INSERT・UPDATE・DDL など）の表の描画にも効く。
- 方言のサブクラス: 登録名が変わるので ``DATABASE_URL`` の変更が要る。

索引の無い DB では、遅くなるのではなく ``no such index`` のエラーになる。固定する索引は、マイグレーションと
モデルの ``ddl_if(dialect="sqlite")`` の両方で作られる前提にしている。
"""

from __future__ import annotations

from sqlalchemy.dialects.sqlite.base import SQLiteCompiler
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.expression import FromClause

INDEXED_BY_PREFIX = "INDEXED BY "


def indexed_by(index_name: str) -> str:
    """``with_hint`` に渡す、索引を固定するヒントの文字列を返す（このモジュールを import すると差し替えが済む）。"""
    return f"{INDEXED_BY_PREFIX}{index_name}"


def _get_from_hint_text(self: SQLCompiler, table: FromClause, text: str | None) -> str | None:
    if text is not None and text.startswith(INDEXED_BY_PREFIX):
        return text
    return None


def install(compiler_cls: type[SQLCompiler] = SQLiteCompiler) -> None:
    """``compiler_cls.get_from_hint_text`` を差し替える。済んでいれば何もしない。

    Raises:
        RuntimeError: 差し替える前の実装が基底（``SQLCompiler``）のままでないとき。``sqlalchemy`` の版に上限が
            無いので、更新で前提が変わったら（SQLite のコンパイラが自前でヒントを扱うようになったら）気づけるようにする。
    """
    current = compiler_cls.get_from_hint_text
    if current is _get_from_hint_text:
        return
    if current is not SQLCompiler.get_from_hint_text:
        raise RuntimeError(
            f"{compiler_cls.__qualname__}.get_from_hint_text is no longer the base implementation; "
            "review vcenter_event_assistant.db.sqlite_hints before upgrading SQLAlchemy"
        )
    setattr(compiler_cls, "get_from_hint_text", _get_from_hint_text)


install()
