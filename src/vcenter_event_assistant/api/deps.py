"""FastAPI 依存性注入ヘルパー。

ルートハンドラ向けに DB セッションを yield する ``get_session`` を提供する。
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.session import get_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """リクエストスコープの非同期 DB セッションを yield する。

    正常終了時は commit、例外時は rollback する。

    Yields:
        非同期 SQLAlchemy セッション。
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
