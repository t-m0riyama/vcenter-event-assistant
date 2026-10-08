"""非同期 DB エンジンとセッションファクトリ。

SQLite / PostgreSQL 向けの engine 生成、``session_scope``、起動時 Alembic マイグレーションを提供する。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant.settings_binding import require_settings


def _sqlite_enable_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite requires per-connection PRAGMA for FK enforcement."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def reset_db() -> None:
    """Dispose engine (for tests)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_engine(*, settings: Settings | None = None):
    """シングルトンの非同期 DB エンジンを返す。

    Args:
        settings: 未指定時は ``require_settings()``（bind 済み Settings）を使用する。

    Returns:
        初回呼び出し時に生成した ``AsyncEngine``。
    """
    global _engine
    if _engine is None:
        s = settings or require_settings()
        url = s.database_url
        if url.startswith("sqlite"):
            _engine = create_async_engine(
                url,
                echo=False,
                connect_args={"check_same_thread": False, "timeout": 30.0},
                poolclass=StaticPool,
            )
            event.listen(_engine.sync_engine, "connect", _sqlite_enable_foreign_keys)
        else:
            _engine = create_async_engine(url, echo=False)
    return _engine


def get_session_factory(
    *, settings: Settings | None = None
) -> async_sessionmaker[AsyncSession]:
    """シングルトンの非同期セッションファクトリを返す。

    Args:
        settings: 未指定時は ``require_settings()``（bind 済み Settings）を使用する。

    Returns:
        ``expire_on_commit=False`` の ``async_sessionmaker``。
    """
    global _session_factory
    if _session_factory is None:
        engine = get_engine(settings=settings)
        _session_factory = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def session_scope(
    settings: Settings | None = None,
) -> AsyncIterator[AsyncSession]:
    """トランザクション付き非同期セッションのコンテキストマネージャ。

    正常終了時は commit、例外時は rollback する。

    Args:
        settings: 未指定時は ``require_settings()``（bind 済み Settings）を使用する。

    Yields:
        非同期 SQLAlchemy セッション。
    """
    factory = get_session_factory(settings=settings)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


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
