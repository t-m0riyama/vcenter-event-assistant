"""SQLite の ``INDEXED BY`` のヒント（Issue #334）: 出力される場所と、されない場所。"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.sqlite.aiosqlite import SQLiteDialect_aiosqlite
from sqlalchemy.dialects.sqlite.base import SQLiteCompiler
from sqlalchemy.orm import aliased

from vcenter_event_assistant.db import sqlite_hints
from vcenter_event_assistant.db.models import MetricSample
from vcenter_event_assistant.services.metric_vcenter_filter import (
    METRIC_COVERING_INDEX,
    pin_metric_covering_index,
)

HINT = f"metric_samples INDEXED BY {METRIC_COVERING_INDEX}"


def _sqlite_sql(stmt: Any, **kw: Any) -> str:
    return str(stmt.compile(dialect=sqlite.dialect(), **kw))


def test_covering_index_constant_matches_model() -> None:
    """定数の索引名が、モデルで SQLite にだけ作る索引（vCenter・指標・期間の順）の名前と一致する。"""
    indexes = {idx.name: idx for idx in MetricSample.__table__.indexes}
    assert METRIC_COVERING_INDEX in indexes
    index = indexes[METRIC_COVERING_INDEX]
    assert [c.name for c in index.columns][:3] == [
        "vcenter_id",
        "metric_key",
        "sampled_at",
    ]


def test_aiosqlite_dialect_uses_the_replaced_compiler() -> None:
    """アプリが使う aiosqlite の方言のコンパイラが、差し替えた関数に解決される（ドライバ側の上書きの見張り）。"""
    compiler_cls = SQLiteDialect_aiosqlite.statement_compiler
    assert getattr(
        compiler_cls.get_from_hint_text, sqlite_hints._INSTALLED_MARKER, False
    )


def test_hint_is_rendered_in_subquery_cte_and_literal_binds() -> None:
    inner = pin_metric_covering_index(
        select(MetricSample.id).where(MetricSample.metric_key == "k")
    )
    assert HINT in _sqlite_sql(inner)
    assert HINT in _sqlite_sql(select(func.count()).select_from(inner.subquery("sub")))
    cte = inner.cte("c")
    assert HINT in _sqlite_sql(select(cte.c.id))
    assert HINT in _sqlite_sql(inner, compile_kwargs={"literal_binds": True})
    # ORM のエンティティを選ぶ select でも、表の FROM に付く
    assert HINT in _sqlite_sql(pin_metric_covering_index(select(MetricSample)))


def test_hint_is_not_rendered_for_alias_or_postgresql() -> None:
    prev = aliased(MetricSample, name="metric_prev")
    stmt = pin_metric_covering_index(
        select(MetricSample.id, prev.id).join(
            prev, prev.vcenter_id == MetricSample.vcenter_id
        )
    )
    sql = _sqlite_sql(stmt)
    assert sql.count("INDEXED BY") == 1, sql
    assert HINT in sql
    assert "INDEXED BY" not in _sqlite_sql(pin_metric_covering_index(select(prev.id)))
    assert "INDEXED BY" not in str(stmt.compile(dialect=postgresql.dialect()))


def test_hint_without_indexed_by_prefix_is_not_rendered() -> None:
    """``INDEXED BY `` で始まらないヒント（方言を指定しないものも）は、SQLite でも出力しない。"""
    stmt = select(MetricSample.id).with_hint(MetricSample.__table__, "FOO")
    assert "FOO" not in _sqlite_sql(stmt)
    stmt = select(MetricSample.id).with_hint(
        MetricSample.__table__, "WITH (NOLOCK)", dialect_name="sqlite"
    )
    assert "NOLOCK" not in _sqlite_sql(stmt)


def test_install_is_idempotent() -> None:
    sqlite_hints.install()
    sqlite_hints.install(SQLiteCompiler)
    assert getattr(
        SQLiteCompiler.get_from_hint_text, sqlite_hints._INSTALLED_MARKER, False
    )


def test_reload_does_not_fail() -> None:
    """モジュールを読み直しても（前の回の関数が残っていても）、差し替え済みとみなして例外にしない。"""
    import importlib

    before = SQLiteCompiler.get_from_hint_text
    importlib.reload(sqlite_hints)
    # 読み直した後も、前の回の関数のまま（差し替え直さない）で、ヒントは出力される
    assert SQLiteCompiler.get_from_hint_text is before
    assert HINT in _sqlite_sql(pin_metric_covering_index(select(MetricSample.id)))


def test_install_fails_when_compiler_defines_its_own_hint_text() -> None:
    """コンパイラが基底の実装のままでなければ（SQLAlchemy の更新で前提が変わったら）例外にする。"""

    class _OwnHintCompiler(SQLiteCompiler):
        def get_from_hint_text(self, table: Any, text: str | None) -> str | None:
            return text

    with pytest.raises(RuntimeError, match="get_from_hint_text"):
        sqlite_hints.install(_OwnHintCompiler)
    # 失敗したときは書き換えない
    assert not getattr(
        _OwnHintCompiler.__dict__["get_from_hint_text"],
        sqlite_hints._INSTALLED_MARKER,
        False,
    )
