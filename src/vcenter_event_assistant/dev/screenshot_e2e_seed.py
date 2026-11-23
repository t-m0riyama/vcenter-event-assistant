"""
Playwright ドキュメント用スクリーンショット向けの最小 DB シード。

環境変数 ``SCREENSHOT_E2E_SEED=1`` のときのみ実行する。本番では無効のままとする。

投入内容: vCenter・イベント種別ガイド・イベントに加え、グラフタブ既定キー向けの
``MetricSample``（``datastore.space.used_bytes`` の時系列）、日次ダイジェスト 1 件、
イベントスコア型アラートルール 1 件と通知履歴 1 行を含む。

タイムライン（既定は直近 1 時間）が 4 種類の出来事と俯瞰グラフを示すよう、対象名つきのイベント、
デモ用ホストの CPU・メモリのサンプル（期間内で始まって終わる超過区間を 1 つずつ）、重大度 error 以上のログも入れる。
名前はすべてデモと分かるもの（実在のホスト・アカウントに見えるものは使わない）。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    DigestRecord,
    EventEntity,
    EventRecord,
    EventTypeGuide,
    LogRecord,
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
                entity_name="demo-vm-03",
                entity_type="VirtualMachine",
                entity_moid="vm-9003",
                entities=[EventEntity(
                    vcenter_id=vc.id, role="vm", position=0, is_primary=True,
                    entity_name="demo-vm-03", entity_type="VirtualMachine", entity_moid="vm-9003",
                )],
                vmware_key=9_001_001,
                notable_score=10,
            ),
        )

        _seed_timeline_demo(session, vc.id, now)

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
                occurred_at=now,
                notified_at=now,
                channel="email",
                success=True,
                delivery_status="succeeded",
                attempt_count=1,
                last_attempt_at=now,
            ),
        )


# タイムラインの既定の期間（直近 1 時間）に収まるよう、取得が数分遅れても外れない 8〜51 分前に置く。
_DEMO_HOSTS = (("host-9001", "demo-esxi-01"), ("host-9002", "demo-esxi-02"))


def _seed_timeline_demo(session: AsyncSession, vcenter_id: uuid.UUID, now: datetime) -> None:
    """タイムライン用のデモ行（イベント・メトリクス・ログ）を足す。"""

    def ago(minutes: float) -> datetime:
        return now - timedelta(minutes=minutes)

    # (何分前, 種別, 対象, スコア, 重大度, メッセージ)。同じ種別・同じ対象の連続（2 件）を 1 組含む。
    events = (
        (46, _EVENT_TYPES[1], "demo-vm-01", 60, "warning", "（デモ）仮想マシンの状態が変わりました"),
        (42, _EVENT_TYPES[0], "demo-vm-02", 5, "info", "（デモ）通常の操作です"),
        (41, _EVENT_TYPES[0], "demo-vm-02", 5, "info", "（デモ）通常の操作です"),
        (33, _EVENT_TYPES[2], "demo-esxi-01", 85, "error", "（デモ）ホストで要確認の事象が起きました"),
        (15, _EVENT_TYPES[1], "demo-vm-01", 30, "warning", "（デモ）仮想マシンの状態が再び変わりました"),
    )
    host_moids = {name: moid for moid, name in _DEMO_HOSTS}
    vm_moids = {"demo-vm-01": "vm-9001", "demo-vm-02": "vm-9002"}
    for i, (minutes, event_type, entity, score, severity, message) in enumerate(events):
        is_host = entity in host_moids
        entity_type = "HostSystem" if is_host else "VirtualMachine"
        entity_moid = host_moids[entity] if is_host else vm_moids[entity]
        session.add(
            EventRecord(
                vcenter_id=vcenter_id,
                occurred_at=ago(minutes),
                event_type=event_type,
                message=message,
                severity=severity,
                entity_name=entity,
                entity_type=entity_type,
                entity_moid=entity_moid,
                entities=[EventEntity(
                    vcenter_id=vcenter_id, role="host" if is_host else "vm", position=0,
                    is_primary=True, entity_name=entity, entity_type=entity_type, entity_moid=entity_moid,
                )],
                vmware_key=9_002_001 + i,
                notable_score=score,
            ),
        )

    # 3 分間隔の CPU・メモリ。CPU は demo-esxi-01 が 30〜21 分前に 80% 以上、
    # メモリは demo-esxi-02 が 36〜27 分前に 85% 以上（どちらも期間内で始まって終わる）。
    cpu_breach = {30, 27, 24, 21}
    mem_breach = {36, 33, 30, 27}
    for step, minutes in enumerate(range(51, 5, -3)):
        for host_index, (moid, name) in enumerate(_DEMO_HOSTS):
            cpu = 35.0 + 3 * ((step + host_index) % 4)
            mem = 55.0 + 2 * ((step + host_index) % 3)
            if host_index == 0 and minutes in cpu_breach:
                cpu = 88.0 + (minutes % 5)
            if host_index == 1 and minutes in mem_breach:
                mem = 91.0 + (minutes % 4)
            for metric_key, value in (("host.cpu.usage_pct", cpu), ("host.mem.usage_pct", mem)):
                session.add(
                    MetricSample(
                        vcenter_id=vcenter_id,
                        sampled_at=ago(minutes),
                        entity_type="HostSystem",
                        entity_moid=moid,
                        entity_name=name,
                        metric_key=metric_key,
                        value=value,
                    ),
                )

    # 重大度 error 以上のログ。同じホスト・同じ種類の連続（3 件。間に別の出来事を挟まない）を 1 組と、別のホストの critical を 1 件。
    logs = (
        (40, "demo-esxi-01", "vmkernel", "error", "（デモ）ストレージへの応答が遅れています"),
        (39, "demo-esxi-01", "vmkernel", "error", "（デモ）ストレージへの応答が遅れています"),
        (38, "demo-esxi-01", "vmkernel", "error", "（デモ）ストレージへの応答が遅れています"),
        (28, "demo-esxi-02", "hostd", "critical", "（デモ）管理サービスが応答しません"),
    )
    for i, (minutes, host, kind, severity, message) in enumerate(logs):
        session.add(
            LogRecord(
                vcenter_id=vcenter_id,
                collector_id="demo.logs",
                source_id=f"demo-source-{host}",
                host=host,
                log_kind=kind,
                file_generation="demo",
                byte_offset=i * 200,
                occurred_at=ago(minutes),
                collected_at=ago(minutes),
                effective_at=ago(minutes),
                severity=severity,
                message=message,
            ),
        )
