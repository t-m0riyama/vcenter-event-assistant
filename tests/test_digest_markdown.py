"""digest_markdown.render_template_digest のテスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from vcenter_event_assistant.api.schemas import HighCpuHostRow, HighMemHostRow
from vcenter_event_assistant.services.digest_context import (
    DigestContext,
    DigestContextEventSnippet,
    DigestEventTypeBucket,
)
from vcenter_event_assistant.services.digest_markdown import render_template_digest


def test_render_includes_event_count_and_title() -> None:
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
    md = render_template_digest(ctx, title="Unit test digest")
    assert "# Unit test digest" in md
    assert "42" in md
    assert "VmPoweredOnEvent" in md
    assert "ホスト CPU" in md
    assert "ホストメモリ" in md
