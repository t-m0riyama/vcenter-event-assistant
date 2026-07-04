"""FastAPI 依存性注入ヘルパー。

ルートハンドラ向けに DB セッションと Settings を提供する。
"""

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.session import get_session_factory
from vcenter_event_assistant.settings import Settings, get_settings


def get_app_settings() -> Settings:
    """リクエストスコープの Settings（環境変数 / ``.env`` 由来）。"""
    return get_settings()


async def get_session(
    settings: Settings = Depends(get_app_settings),
) -> AsyncIterator[AsyncSession]:
    """リクエストスコープの非同期 DB セッションを yield する。

    正常終了時は commit、例外時は rollback する。

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
