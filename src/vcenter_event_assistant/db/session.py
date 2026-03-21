"""Async engine and session factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from vcenter_event_assistant.db.base import Base
from vcenter_event_assistant.settings import Settings, get_settings


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
    global _engine
    if _engine is None:
        s = settings or get_settings()
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


def get_session_factory(*, settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        engine = get_engine(settings=settings)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return _session_factory


@asynccontextmanager
async def session_scope(settings: Settings | None = None) -> AsyncIterator[AsyncSession]:
    factory = get_session_factory(settings=settings)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db(settings: Settings | None = None) -> None:
    engine = get_engine(settings=settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
