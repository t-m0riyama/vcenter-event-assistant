"""digest_run.run_digest_once のテスト（LLM なし）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vcenter_event_assistant.db.models import DigestRecord, EventRecord, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.digest.digest_run import run_digest_once
from vcenter_event_assistant.settings import Settings


def _patch_digest_run_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    def getter() -> Settings:
        return settings

    monkeypatch.setattr("vcenter_event_assistant.services.digest.digest_run.get_settings", getter)
    monkeypatch.setattr("vcenter_event_assistant.services.digest.digest_markdown.get_settings", getter)
    monkeypatch.setattr("vcenter_event_assistant.services.digest.digest_llm.get_settings", getter)


@pytest.mark.asyncio
async def test_run_digest_once_persists_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    vid = uuid.uuid4()
    base = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
    fr = base - timedelta(hours=1)
    to = base + timedelta(hours=1)

    async with session_scope() as session:
        session.add(
            VCenter(
                id=vid,
                name="run-vc",
                host="h",
                port=443,
                username="u",
                password="p",
                is_enabled=True,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="VmPoweredOnEvent",
                message="x",
                severity="info",
                vmware_key=1,
                notable_score=1,
            )
        )

    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key=None,
    )
    _patch_digest_run_settings(monkeypatch, settings)

    async with session_scope() as session:
        row = await run_digest_once(
            session,
            kind="daily",
            from_utc=fr,
            to_utc=to,
        )
        assert row.id is not None
        assert row.status == "ok"
        assert row.kind == "daily"
        assert "# vCenter ダイジェスト（日次）" in row.body_markdown
        assert "VmPoweredOnEvent" in row.body_markdown
        assert row.llm_model is None
        assert row.error_message is None

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(select(DigestRecord).where(DigestRecord.id == row.id))
        loaded = res.scalar_one()
        assert loaded.body_markdown == row.body_markdown


@pytest.mark.asyncio
async def test_run_digest_once_template_error_sets_status_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = tmp_path / "bad.j2"
    bad.write_text("{% unclosed", encoding="utf-8")

    vid = uuid.uuid4()
    base = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
    fr = base - timedelta(hours=1)
    to = base + timedelta(hours=1)

    async with session_scope() as session:
        session.add(
            VCenter(
                id=vid,
                name="run-vc",
                host="h",
                port=443,
                username="u",
                password="p",
                is_enabled=True,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="VmPoweredOnEvent",
                message="x",
                severity="info",
                vmware_key=1,
                notable_score=1,
            )
        )

    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key=None,
        digest_template_path=str(bad),
    )
    _patch_digest_run_settings(monkeypatch, settings)

    async with session_scope() as session:
        row = await run_digest_once(
            session,
            kind="daily",
            from_utc=fr,
            to_utc=to,
        )
        assert row.status == "error"
        assert row.body_markdown == ""
        assert row.error_message is not None
        assert "digest template:" in (row.error_message or "")
        assert row.llm_model is None
