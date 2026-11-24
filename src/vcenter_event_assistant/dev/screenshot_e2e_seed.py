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
from vcenter_event_assistant.dev.inventory_seed import seed_inventory
from vcenter_event_assistant.mocks.mock_inventory import (
    SCREENSHOT_DATASTORE,
    SCREENSHOT_HOSTS,
    SCREENSHOT_VCENTER_NAME,
    SCREENSHOT_VMS,
)
from vcenter_event_assistant.plugins.builtin import EventsCollector, TasksCollector
from vcenter_event_assistant.rules.notable import final_notable_score

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
        res = await session.execute(
            select(VCenter).where(VCenter.name == SCREENSHOT_VCENTER_NAME)
        )
        if existing := res.scalar_one_or_none():
            await seed_inventory(session, existing, datetime.now(timezone.utc))
            return

        vc = VCenter(
            name=SCREENSHOT_VCENTER_NAME,
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
        await seed_inventory(session, vc, now)
        vm_moid, vm_name = SCREENSHOT_VMS[2]
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=now,
                event_type=_EVENT_TYPES[0],
                message="（デモ）スクリーンショット用イベント",
                severity="info",
                entity_name=vm_name,
                entity_type="VirtualMachine",
                entity_moid=vm_moid,
                entities=[
                    EventEntity(
                        vcenter_id=vc.id,
                        role="vm",
                        position=0,
                        is_primary=True,
                        entity_name=vm_name,
                        entity_type="VirtualMachine",
                        entity_moid=vm_moid,
                    )
                ],
                vmware_key=9_001_001,
                notable_score=10,
            ),
        )

        _seed_timeline_demo(session, vc.id, now)

        # グラフタブはキー一覧の先頭（`datastore.space.used_bytes`）が既定選択になるため、その系列を投入する。
        _doc_metric_key = "datastore.space.used_bytes"
        ds_moid, ds_name = SCREENSHOT_DATASTORE
        for i in range(32):
            sampled = now - timedelta(minutes=2 * (31 - i))
            session.add(
                MetricSample(
                    vcenter_id=vc.id,
                    sampled_at=sampled,
                    entity_type="Datastore",
                    entity_moid=ds_moid,
                    entity_name=ds_name,
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


def _seed_timeline_demo(session: AsyncSession, vcenter_id: uuid.UUID, now: datetime) -> None:
    """タイムライン用のデモ行（イベント・メトリクス・ログ）を足す。"""

    def ago(minutes: float) -> datetime:
        return now - timedelta(minutes=minutes)

    # 既定の期間（直近 1 時間）に収まるよう、タイムライン用の行を 6〜54 分前に置く。
    # (何分前, 種別, 対象, スコア, 重大度, メッセージ)。同じ種別・同じ対象の連続（2 件）を 1 組含む。
    events = (
        (46, _EVENT_TYPES[1], "demo-vm-01", 60, "warning", "（デモ）仮想マシンの状態が変わりました"),
        (42, _EVENT_TYPES[0], "demo-vm-02", 5, "info", "（デモ）通常の操作です"),
        (41, _EVENT_TYPES[0], "demo-vm-02", 5, "info", "（デモ）通常の操作です"),
        (33, _EVENT_TYPES[2], "demo-esxi-01", 85, "error", "（デモ）ホストで要確認の事象が起きました"),
        (15, _EVENT_TYPES[1], "demo-vm-01", 30, "warning", "（デモ）仮想マシンの状態が再び変わりました"),
        # 切断の行は既存のイベントより前に置き、通常の採点を使う。
        *((minutes, "vim.event.HostConnectionLostEvent", "demo-esxi-01", None, "info",
           "（デモ）ホストと vCenter の接続が切れました") for minutes in (54, 51, 48)),
    )
    # ホストのエラー（33 分前）より前に構成変更を入れる。
    config_changes = (
        (53, "vim.event.EnteredMaintenanceModeEvent", "demo-esxi-01", "メンテナンスモードに入りました", None),
        (50, "vim.event.ExitMaintenanceModeEvent", "demo-esxi-01", "メンテナンスモードを出ました", None),
        (45, "vim.event.VmReconfiguredEvent", "demo-vm-01", "仮想マシンを再構成しました", 9_003_001),
        (44, "task.success.VirtualMachine.reconfigure", "demo-vm-01", "再構成のタスクが完了しました", 9_003_001),
    )
    config_metadata = {event_type: chain_id for _, event_type, _, _, chain_id in config_changes}
    events += tuple(
        (minutes, event_type, entity, 0, "info", f"（デモ）{message}")
        for minutes, event_type, entity, message, _ in config_changes
    )
    host_moids = {name: moid for moid, name in SCREENSHOT_HOSTS}
    vm_moids = {name: moid for moid, name in SCREENSHOT_VMS}
    for i, (minutes, event_type, entity, score, severity, message) in enumerate(events):
        if score is None:
            score = final_notable_score(event_type=event_type, severity=severity, message=message)
        is_host = entity in host_moids
        entity_type = "HostSystem" if is_host else "VirtualMachine"
        entity_moid = host_moids[entity] if is_host else vm_moids[entity]
        session.add(
            EventRecord(
                vcenter_id=vcenter_id,
                collector_id=(
                    TasksCollector.manifest.id if event_type.startswith("task.") else EventsCollector.manifest.id
                ),
                occurred_at=ago(minutes),
                event_type=event_type,
                message=message,
                severity=severity,
                user_name="demo-operator" if event_type in config_metadata else None,
                chain_id=config_metadata.get(event_type),
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
        for host_index, (moid, name) in enumerate(SCREENSHOT_HOSTS):
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
