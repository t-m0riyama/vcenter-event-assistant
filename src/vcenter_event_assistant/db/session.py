"""非同期 DB エンジンとセッションファクトリ。

SQLite / PostgreSQL 向けの engine 生成、``session_scope``、起動時 Alembic マイグレーションを提供する。
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import aiosqlite
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool, StaticPool

from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.settings_binding import require_settings


def _sqlite_enable_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite requires per-connection PRAGMA for FK enforcement."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _sqlite_engine(url: str, **options) -> AsyncEngine:
    engine = create_async_engine(
        url,
        json_serializer=_json_serializer,
        connect_args={"check_same_thread": False, "timeout": 30.0},
        **options,
    )
    event.listen(engine.sync_engine, "connect", _sqlite_enable_foreign_keys)
    return engine


_engine = None
_isolated_memory_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def reset_db() -> None:
    """Dispose engine (for tests)."""
    global _engine, _isolated_memory_engine, _session_factory
    if _isolated_memory_engine is not None:
        await _isolated_memory_engine.dispose()
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _isolated_memory_engine = None
    _session_factory = None


def get_engine(*, settings: Settings | None = None):
    """シングルトンの非同期 DB エンジンを返す。

    Args:
        settings: 未指定時は ``require_settings()``（bind 済み Settings）を使用する。

    Returns:
        初回呼び出し時に生成した ``AsyncEngine``。
    """
    global _engine, _isolated_memory_engine
    if _engine is None:
        s = settings or require_settings()
        url = s.database_url
        if url.startswith("sqlite"):
            sqlite_url = make_url(url)
            # URL.query ではなく、方言が組み立てた SQLite ネイティブの接続文字列を判定する。
            (filename,), driver_options = sqlite_url.get_dialect()().create_connect_args(sqlite_url)
            in_memory = filename == ":memory:"
            if driver_options.get("uri") and filename.startswith("file:"):
                uri = urlsplit(filename)
                uri_path = unquote(uri.path).partition("\0")[0]
                options: dict[str, str] = {}
                for option in uri.query.split("&"):
                    key, _, value = option.partition("=")
                    options[unquote(key).partition("\0")[0]] = unquote(value).partition("\0")[0]
                in_memory = (
                    uri_path in ("", ":memory:")
                    or options.get("mode") == "memory"
                    or options.get("vfs") == "memdb"
                )
            if in_memory:
                # Both pools access the same in-memory data. The separate pool keeps
                # an isolated transaction off the normal StaticPool connection.
                memory_uri = f"file:/vea-{uuid4().hex}?vfs=memdb"

                async def connect_memory() -> aiosqlite.Connection:
                    return await aiosqlite.connect(
                        memory_uri, uri=True, check_same_thread=False, timeout=30.0
                    )

                _engine = _sqlite_engine(url, async_creator=connect_memory, poolclass=StaticPool)
                _isolated_memory_engine = _sqlite_engine(
                    url, async_creator=connect_memory, poolclass=AsyncAdaptedQueuePool
                )
            else:
                _engine = _sqlite_engine(url)
        else:
            _engine = create_async_engine(url, echo=False, json_serializer=_json_serializer)
    return _engine


def _json_serializer(value: object) -> str:
    """JSON 列の保存形式。日本語を ``\\uXXXX`` に展開しない（1 文字 6 バイトになり、結果の保存で大きくなるため）。"""
    return json.dumps(value, ensure_ascii=False)


def get_session_factory(*, settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """シングルトンの非同期セッションファクトリを返す。

    Args:
        settings: 未指定時は ``require_settings()``（bind 済み Settings）を使用する。

    Returns:
        ``expire_on_commit=False`` の ``async_sessionmaker``。
    """
    global _session_factory
    if _session_factory is None:
        engine = get_engine(settings=settings)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return _session_factory


@asynccontextmanager
async def session_scope(
    settings: Settings | None = None, *, isolate_memory: bool = False
) -> AsyncIterator[AsyncSession]:
    """トランザクション付き非同期セッションのコンテキストマネージャ。

    正常終了時は commit、例外時は rollback する。

    Args:
        settings: 未指定時は ``require_settings()``（bind 済み Settings）を使用する。
        isolate_memory: SQLite インメモリ DB でトランザクション専用の接続を借りる。

    Yields:
        非同期 SQLAlchemy セッション。
    """
    async with open_session(settings, isolate_memory=isolate_memory) as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def open_session(
    settings: Settings | None = None, *, isolate_memory: bool = False,
) -> AsyncIterator[AsyncSession]:
    """commit の時点を呼び出し元で管理するセッション。"""
    factory = get_session_factory(settings=settings)
    session = (
        factory(bind=_isolated_memory_engine)
        if isolate_memory and _isolated_memory_engine is not None
        else factory()
    )
    async with session:
        yield session


async def init_db(settings: Settings | None = None) -> None:
    """排他制御・SQLite バックアップ付きで Alembic スキーマを最新化する。

    - 最新 DB: 変更なし。それ以外の ``alembic_version`` あり DB: ``upgrade head``
    - 空 DB: ``upgrade head``（新規作成）
    - 旧 DB（``alembic_version`` なし）: 列 fingerprint で ``stamp`` 後 ``upgrade head``
      （曖昧な場合は :class:`LegacySchemaStampError` で起動 abort）

    Args:
        settings: 未指定時は ``require_settings()``（bind 済み Settings）を使用する。
    """
    from vcenter_event_assistant.db.startup_migration import run_startup_migration

    s = settings or require_settings()
    await run_startup_migration(get_engine(settings=s), settings=s)
