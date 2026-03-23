"""digest_records テーブル / DigestRecord ORM のスモークテスト。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from vcenter_event_assistant.db.models import DigestRecord


@pytest.mark.asyncio
async def test_digest_records_empty_then_insert() -> None:
    from vcenter_event_assistant.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        n = await session.scalar(select(func.count()).select_from(DigestRecord))
        assert int(n or 0) == 0

        row = DigestRecord(
            period_start=datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc),
            period_end=datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc),
            kind="daily",
            body_markdown="# test",
            status="ok",
            error_message=None,
            llm_model=None,
        )
        session.add(row)
        await session.commit()

    async with factory() as session:
        res = await session.execute(select(DigestRecord))
        rows = list(res.scalars().all())
        assert len(rows) == 1
        assert rows[0].kind == "daily"
        assert rows[0].status == "ok"
