"""
Playwright ドキュメント用スクリーンショット向けの最小 DB シード。

環境変数 ``SCREENSHOT_E2E_SEED=1`` のときのみ実行する。本番では無効のままとする。

投入内容: vCenter・イベント種別ガイド・イベントに加え、グラフタブ既定キー向けの
``MetricSample``（``datastore.space.used_bytes`` の時系列）、日次ダイジェスト 1 件、
イベントスコア型アラートルール 1 件と通知履歴 1 行を含む。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    DigestRecord,
    EventRecord,
    EventTypeGuide,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope

_SCREENSHOT_VC_NAME = "screenshot-e2e-vc"
_EVENT_TYPES = (
    "vim.event.ScreenshotDemoEvent",
    "vim.event.ScreenshotDemoEventB",
    "vim.event.ScreenshotDemoEventC",
)


async def run_screenshot_e2e_seed_if_enabled() -> None:
    """``SCREENSHOT_E2E_SEED=1`` のとき、未シードならドキュメント用の最小行を挿入する。"""
    if os.environ.get("SCREENSHOT_E2E_SEED") != "1":
        return

    async with session_scope() as session:
        res = await session.execute(select(VCenter).where(VCenter.name == _SCREENSHOT_VC_NAME))
        if res.scalar_one_or_none() is not None:
            return

        vc = VCenter(
            name=_SCREENSHOT_VC_NAME,
            host="127.0.0.1",
            port=443,
            username="u",
            password="p",
            is_enabled=True,
        )
        session.add(vc)
        await session.flush()

        guides = (
            EventTypeGuide(
                event_type=_EVENT_TYPES[0],
                general_meaning="（デモ）代表的な意味の説明です。",
                typical_causes="（デモ）想定される原因です。",
                remediation="（デモ）対処の例です。",
                action_required=False,
            ),
            EventTypeGuide(
                event_type=_EVENT_TYPES[1],
                general_meaning="（デモ）別種別の意味。",
                typical_causes="（デモ）原因。",
                remediation="（デモ）対処。",
                action_required=False,
            ),
            EventTypeGuide(
                event_type=_EVENT_TYPES[2],
                general_meaning="（デモ）三番目の種別。",
                typical_causes="（デモ）原因。",
                remediation="（デモ）対処。",
                action_required=False,
            ),
        )
        for g in guides:
            session.add(g)

        now = datetime.now(timezone.utc)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=now,
                event_type=_EVENT_TYPES[0],
                message="（デモ）スクリーンショット用イベント",
                severity="info",
                vmware_key=9_001_001,
                notable_score=10,
            ),
        )

        # グラフタブはキー一覧の先頭（`datastore.space.used_bytes`）が既定選択になるため、その系列を投入する。
        _doc_metric_key = "datastore.space.used_bytes"
        _doc_entity_moid = "datastore-1001"
        for i in range(32):
            sampled = now - timedelta(minutes=2 * (31 - i))
            session.add(
                MetricSample(
                    vcenter_id=vc.id,
                    sampled_at=sampled,
                    entity_type="Datastore",
                    entity_moid=_doc_entity_moid,
                    entity_name="demo-datastore",
                    metric_key=_doc_metric_key,
                    value=float(1_000_000_000 + i * 12_500_000),
                ),
            )

        period_end = now.replace(minute=0, second=0, microsecond=0)
        period_start = period_end - timedelta(days=1)
        session.add(
            DigestRecord(
                period_start=period_start,
                period_end=period_end,
                kind="daily",
                body_markdown=(
                    "# 日次ダイジェスト（デモ）\n\n"
                    "## 概要\n\nスクリーンショット用の最小サンプルです。\n"
                ),
                status="ok",
                llm_model=None,
                created_at=now,
            ),
        )

        rule = AlertRule(
            name="デモ: イベントスコア",
            rule_type="event_score",
            is_enabled=True,
            alert_level="warning",
            config={"threshold": 50, "cooldown_minutes": 60},
        )
        session.add(rule)
        await session.flush()
        session.add(
            AlertHistory(
                rule_id=rule.id,
                alert_level="warning",
                state="firing",
                context_key=_EVENT_TYPES[0],
                notified_at=now,
                channel="email",
                success=True,
                delivery_status="succeeded",
                attempt_count=1,
                last_attempt_at=now,
            ),
        )
