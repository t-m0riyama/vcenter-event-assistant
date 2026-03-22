"""Async engine and session factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
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


async def _ensure_events_user_comment_column(engine: AsyncEngine) -> None:
    """Add ``events.user_comment`` when DB predates that column (``create_all`` does not alter tables)."""

    def sync_check(sync_conn) -> None:
        insp = inspect(sync_conn)
        if not insp.has_table("events"):
            return
        cols = [c["name"] for c in insp.get_columns("events")]
        if "user_comment" in cols:
            return
        sync_conn.execute(
            text("ALTER TABLE events ADD COLUMN user_comment TEXT"),
        )

    async with engine.begin() as conn:
        await conn.run_sync(sync_check)


async def ensure_event_type_guides_action_required_column(engine: AsyncEngine) -> None:
    """``event_type_guides.action_required`` を、旧 DB（列なし）向けに追加する。``create_all`` は既存テーブルを変更しない。

    SQLite は ``inspect.get_columns`` が期待どおりでないケースがあるため、列の有無は ``PRAGMA table_info`` で判定する。
    """

    def sync_check(sync_conn) -> None:
        insp = inspect(sync_conn)
        if not insp.has_table("event_type_guides"):
            return
        dialect = sync_conn.dialect.name
        if dialect == "sqlite":
            res = sync_conn.execute(text("PRAGMA table_info(event_type_guides)"))
            cols = [row[1] for row in res.fetchall()]
        else:
            cols = [c["name"] for c in insp.get_columns("event_type_guides")]
        if "action_required" in cols:
            return
        if dialect == "postgresql":
            sync_conn.execute(
                text(
                    "ALTER TABLE event_type_guides ADD COLUMN action_required BOOLEAN NOT NULL DEFAULT false"
                ),
            )
        else:
            # SQLite 等: BOOLEAN は 0/1
            sync_conn.execute(
                text(
                    "ALTER TABLE event_type_guides ADD COLUMN action_required BOOLEAN NOT NULL DEFAULT 0"
                ),
            )

    async with engine.begin() as conn:
        await conn.run_sync(sync_check)


async def init_db(settings: Settings | None = None) -> None:
    # すべてのモデルを Base.metadata に登録してから create_all する
    import vcenter_event_assistant.db.models  # noqa: F401

    engine = get_engine(settings=settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_events_user_comment_column(engine)
    await ensure_event_type_guides_action_required_column(engine)
