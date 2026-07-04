#!/usr/bin/env python3
"""開発専用 SQLite（既定: ./data/vea.dev.db）を初期化する。

``./data/vea.db``（手元の永続データ）を汚さないため、ローカル開発・エージェント検証は
本スクリプトまたは ``DATABASE_URL=.../vea.dev.db`` を使う。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

DEFAULT_DEV_DATABASE_URL = "sqlite+aiosqlite:///./data/vea.dev.db"


def resolve_dev_database_url() -> str:
    """開発専用 DB URL。シェルの ``DATABASE_URL``（vea.db 向け）は無視する。"""
    return os.environ.get("VEA_DEV_DATABASE_URL", DEFAULT_DEV_DATABASE_URL)


async def main() -> None:
    url = resolve_dev_database_url()
    os.environ["DATABASE_URL"] = url
    Path("./data").mkdir(parents=True, exist_ok=True)

    from vcenter_event_assistant.settings import get_settings

    get_settings.cache_clear()

    from vcenter_event_assistant.db.alembic_runner import ALEMBIC_HEAD, get_applied_alembic_revision
    from vcenter_event_assistant.db.session import get_engine, init_db, reset_db

    await reset_db()
    await init_db()
    engine = get_engine()
    revision = await get_applied_alembic_revision(engine)
    await reset_db()

    print(f"DATABASE_URL={url}")
    print(f"alembic head={ALEMBIC_HEAD} applied={revision}")


if __name__ == "__main__":
    asyncio.run(main())
