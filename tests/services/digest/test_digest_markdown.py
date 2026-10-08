"""digest_markdown.render_digest_markdown のテスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vcenter_event_assistant.api.schemas import HighCpuHostRow, HighMemHostRow
from vcenter_event_assistant.services.digest.digest_context import (
    DigestContext,
    DigestEventTypeBucket,
    DigestNotableEventGroup,
)
from vcenter_event_assistant.services.digest.digest_markdown import render_digest_markdown
from vcenter_event_assistant.settings import Settings


def _minimal_settings(**kwargs: object) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key=None,
        **kwargs,
    )


def _patch_digest_markdown_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest.digest_markdown.require_settings",
        lambda: settings,
    )


def _empty_ctx() -> DigestContext:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    return DigestContext(
        from_utc=t0,
        to_utc=t1,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_event_groups=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )


def test_weekly_template_path_used_when_kind_is_weekly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = tmp_path / "w.j2"
    w.write_text("# WEEKLY_ONLY\n", encoding="utf-8")
    ctx = _empty_ctx()
    _patch_digest_markdown_settings(
        monkeypatch,
        _minimal_settings(digest_template_weekly_path=str(w)),
    )
    md = render_digest_markdown(ctx, kind="weekly")
    assert "WEEKLY_ONLY" in md


def test_weekly_template_path_not_used_when_kind_is_daily(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = tmp_path / "w.j2"
    w.write_text("# WEEKLY_ONLY\n", encoding="utf-8")
    ctx = _empty_ctx()
    _patch_digest_markdown_settings(
        monkeypatch,
        _minimal_settings(digest_template_weekly_path=str(w)),
    )
    md = render_digest_markdown(ctx, kind="daily")
    assert "# vCenter ダイジェスト（日次）" in md
    assert "WEEKLY_ONLY" not in md


def test_weekly_falls_back_to_digest_template_dir_when_weekly_path_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tpl = tmp_path / "custom.j2"
    tpl.write_text("# DIR_WEEKLY\n{{ kind }}\n", encoding="utf-8")
    ctx = _empty_ctx()
    _patch_digest_markdown_settings(
        monkeypatch,
        _minimal_settings(
            digest_template_dir=str(tmp_path),
            digest_template_file="custom.j2",
        ),
    )
    md = render_digest_markdown(ctx, kind="weekly")
    assert "DIR_WEEKLY" in md
    assert "weekly" in md


def test_weekly_template_path_missing_file_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _empty_ctx()
    _patch_digest_markdown_settings(
        monkeypatch,
        _minimal_settings(digest_template_weekly_path="/nonexistent/weekly.j2"),
    )
    with pytest.raises(FileNotFoundError):
        render_digest_markdown(ctx, kind="weekly")


def test_monthly_template_path_used_when_kind_is_monthly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = tmp_path / "m.j2"
    m.write_text("# MONTHLY_ONLY\n", encoding="utf-8")
    ctx = _empty_ctx()
    _patch_digest_markdown_settings(
        monkeypatch,
        _minimal_settings(digest_template_monthly_path=str(m)),
    )
    md = render_digest_markdown(ctx, kind="monthly")
    assert "MONTHLY_ONLY" in md


def test_monthly_template_path_not_used_when_kind_is_daily(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = tmp_path / "m.j2"
    m.write_text("# MONTHLY_ONLY\n", encoding="utf-8")
    ctx = _empty_ctx()
    _patch_digest_markdown_settings(
        monkeypatch,
        _minimal_settings(digest_template_monthly_path=str(m)),
    )
    md = render_digest_markdown(ctx, kind="daily")
    assert "# vCenter ダイジェスト（日次）" in md
    assert "MONTHLY_ONLY" not in md


def test_monthly_template_path_missing_file_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _empty_ctx()
    _patch_digest_markdown_settings(
        monkeypatch,
        _minimal_settings(digest_template_monthly_path="/nonexistent/monthly.j2"),
    )
    with pytest.raises(FileNotFoundError):
        render_digest_markdown(ctx, kind="monthly")


def test_render_digest_markdown_uses_kind_not_title(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t1,
        vcenter_count=1,
        total_events=42,
        notable_events_count=3,
        top_notable_event_groups=[
            DigestNotableEventGroup(
                event_type="VmPoweredOnEvent",
                occurrence_count=1,
                notable_score=10,
                occurred_at_first=t0,
                occurred_at_last=t0,
                entity_name="vm-1",
                message="hello",
            )
        ],
        top_event_types=[
            DigestEventTypeBucket(event_type="VmPoweredOnEvent", event_count=40, max_notable_score=10)
        ],
        high_cpu_hosts=[
            HighCpuHostRow(
                vcenter_id=str(uuid.uuid4()),
                vcenter_label="ラベルCPU",
                entity_name="h1",
                entity_moid="m",
                value=90.0,
                sampled_at=t0,
            )
        ],
        high_mem_hosts=[
            HighMemHostRow(
                vcenter_id=str(uuid.uuid4()),
                vcenter_label="ラベルMEM",
                entity_name="h2",
                entity_moid="m2",
                value=80.0,
                sampled_at=t0,
            )
        ],
    )
    _patch_digest_markdown_settings(monkeypatch, _minimal_settings())
    md = render_digest_markdown(ctx, kind="daily")
    assert "# vCenter ダイジェスト（日次）" in md
    assert "42" in md
    assert "VmPoweredOnEvent" in md
    assert "1 回発生" in md
    assert "要注意イベント" in md
    assert "ホスト CPU" in md
    assert "ホストメモリ" in md
    assert "ラベルCPU" in md
    assert "ラベルMEM" in md


def test_invalid_display_timezone_warns_and_falls_back(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t1,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_event_groups=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    _patch_digest_markdown_settings(
        monkeypatch,
        _minimal_settings(digest_display_timezone="Not/A/Zone"),
    )
    caplog.set_level("WARNING", logger="vcenter_event_assistant.services.digest.digest_timezone")
    md = render_digest_markdown(ctx, kind="daily")
    assert "無効な DIGEST_DISPLAY_TIMEZONE" in caplog.text
    assert "+00:00" in md or "Z" in md


def test_render_digest_markdown_uses_digest_template_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        top_notable_event_groups=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    _patch_digest_markdown_settings(
        monkeypatch,
        _minimal_settings(
            digest_template_dir=str(tmp_path),
            digest_template_file="custom.j2",
            digest_display_timezone="UTC",
        ),
    )
    md = render_digest_markdown(ctx, kind="daily")
    assert "DIR_BRANCH_OK" in md
    assert "daily" in md
    assert "UTC" in md


def test_digest_template_path_missing_file_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t1,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_event_groups=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    _patch_digest_markdown_settings(
        monkeypatch,
        _minimal_settings(digest_template_path="/nonexistent/digest.md.j2"),
    )
    with pytest.raises(FileNotFoundError):
        render_digest_markdown(ctx, kind="daily")
