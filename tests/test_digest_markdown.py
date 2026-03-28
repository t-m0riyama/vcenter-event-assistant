"""digest_markdown.render_digest_markdown のテスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vcenter_event_assistant.api.schemas import HighCpuHostRow, HighMemHostRow
from vcenter_event_assistant.services.digest_context import (
    DigestContext,
    DigestContextEventSnippet,
    DigestEventTypeBucket,
)
from vcenter_event_assistant.services.digest_markdown import render_digest_markdown
from vcenter_event_assistant.settings import Settings


def _minimal_settings(**kwargs: object) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key=None,
        **kwargs,
    )


def test_render_digest_markdown_uses_kind_not_title() -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t1,
        vcenter_count=1,
        total_events=42,
        notable_events_count=3,
        top_notable_events=[
            DigestContextEventSnippet(
                id=1,
                vcenter_id=uuid.uuid4(),
                occurred_at=t0,
                event_type="VmPoweredOnEvent",
                message="hello",
                severity="info",
                entity_name="vm-1",
                notable_score=10,
            )
        ],
        top_event_types=[
            DigestEventTypeBucket(event_type="VmPoweredOnEvent", event_count=40, max_notable_score=10)
        ],
        high_cpu_hosts=[
            HighCpuHostRow(
                vcenter_id=str(uuid.uuid4()),
                entity_name="h1",
                entity_moid="m",
                value=90.0,
                sampled_at=t0,
            )
        ],
        high_mem_hosts=[
            HighMemHostRow(
                vcenter_id=str(uuid.uuid4()),
                entity_name="h2",
                entity_moid="m2",
                value=80.0,
                sampled_at=t0,
            )
        ],
    )
    md = render_digest_markdown(ctx, kind="daily", settings=_minimal_settings())
    assert "# vCenter ダイジェスト（日次）" in md
    assert "42" in md
    assert "VmPoweredOnEvent" in md
    assert "ホスト CPU" in md
    assert "ホストメモリ" in md


def test_invalid_display_timezone_warns_and_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t1,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_events=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    caplog.set_level("WARNING", logger="vcenter_event_assistant.services.digest_markdown")
    md = render_digest_markdown(
        ctx,
        kind="daily",
        settings=_minimal_settings(digest_display_timezone="Not/A/Zone"),
    )
    assert "無効な DIGEST_DISPLAY_TIMEZONE" in caplog.text
    assert "+00:00" in md or "Z" in md


def test_render_digest_markdown_uses_digest_template_dir(tmp_path: Path) -> None:
    """``DIGEST_TEMPLATE_DIR`` + ``DIGEST_TEMPLATE_FILE`` 分岐（PATH 空）を検証する。"""
    tpl = tmp_path / "custom.j2"
    tpl.write_text("# DIR_BRANCH_OK\n{{ kind }} / {{ display_timezone }}\n", encoding="utf-8")
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t1,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_events=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    md = render_digest_markdown(
        ctx,
        kind="daily",
        settings=_minimal_settings(
            digest_template_dir=str(tmp_path),
            digest_template_file="custom.j2",
        ),
    )
    assert "DIR_BRANCH_OK" in md
    assert "daily" in md
    assert "UTC" in md


def test_digest_template_path_missing_file_raises() -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t1,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_events=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    with pytest.raises(FileNotFoundError):
        render_digest_markdown(
            ctx,
            kind="daily",
            settings=_minimal_settings(digest_template_path="/nonexistent/digest.md.j2"),
        )
