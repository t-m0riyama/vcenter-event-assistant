"""
Playwright ドキュメント用スクリーンショット向けの最小 DB シード。

環境変数 ``SCREENSHOT_E2E_SEED=1`` のときのみ実行する。本番では無効のままとする。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import select

from vcenter_event_assistant.db.models import EventRecord, EventTypeGuide, VCenter
from vcenter_event_assistant.db.session import session_scope

_SCREENSHOT_VC_NAME = "screenshot-e2e-vc"
_EVENT_TYPES = (
    "vim.event.ScreenshotDemoEvent",
    "vim.event.ScreenshotDemoEventB",
    "vim.event.ScreenshotDemoEventC",
)


async def run_screenshot_e2e_seed_if_enabled() -> None:
    """``SCREENSHOT_E2E_SEED=1`` のとき、未シードなら vCenter・ガイド・イベントを挿入する。"""
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
