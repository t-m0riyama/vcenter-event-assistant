#!/usr/bin/env python3
"""開発専用 DB 向けスモークテスト（vCenter 削除 + 関連 events CASCADE）。"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

DEFAULT_DEV_DATABASE_URL = "sqlite+aiosqlite:///./data/vea.dev.db"


def resolve_dev_database_url() -> str:
    """開発専用 DB URL。シェルの ``DATABASE_URL``（vea.db 向け）は無視する。"""
    return os.environ.get("VEA_DEV_DATABASE_URL", DEFAULT_DEV_DATABASE_URL)


async def main() -> None:
    url = resolve_dev_database_url()
    os.environ["DATABASE_URL"] = url

    from vcenter_event_assistant.settings import get_settings

    get_settings.cache_clear()

    from vcenter_event_assistant.db.models import EventRecord, VCenter
    from vcenter_event_assistant.db.session import init_db, reset_db, session_scope
    from sqlalchemy import func, select

    await reset_db()
    await init_db()

    vc_id = uuid.uuid4()
    async with session_scope() as session:
        session.add(
            VCenter(
                id=vc_id,
                name="dev-smoke-vc",
                host="dev.example.local",
                username="u",
                password="p",
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vc_id,
                occurred_at=datetime.now(timezone.utc),
                event_type="smoke.test",
                message="dev db smoke",
                vmware_key=1,
                notable_score=0,
            )
        )

    async with session_scope() as session:
        vc = await session.get(VCenter, vc_id)
        assert vc is not None
        await session.delete(vc)

    async with session_scope() as session:
        vc_count = await session.scalar(select(func.count()).select_from(VCenter))
        ev_count = await session.scalar(select(func.count()).select_from(EventRecord))

    await reset_db()
    get_settings.cache_clear()

    assert vc_count == 0
    assert ev_count == 0
    print(f"OK: dev db smoke passed ({url})")


if __name__ == "__main__":
    asyncio.run(main())
