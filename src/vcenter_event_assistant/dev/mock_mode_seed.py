"""
``MOCK_MODE=1`` 時のデモ用 DB シード。

投入内容: デモ vCenter・イベント種別ガイド・イベント・ホスト／Datastore メトリクス・
簡易アラートルール。同一 vCenter 名が既にあれば何もしない（冪等）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from vcenter_event_assistant.db.models import (
    AlertRule,
    EventRecord,
    EventTypeGuide,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.settings import get_settings

logger = logging.getLogger(__name__)

_MOCK_VC_NAME = "mock-demo-vc"
_EVENT_TYPES = (
    "vim.event.VmPoweredOnEvent",
    "vim.event.AlarmStatusChangedEvent",
    "vim.event.HostConnectionLostEvent",
)


async def run_mock_mode_seed_if_enabled() -> None:
    """``settings.mock_mode`` のとき、未シードならデモデータを挿入する。"""
    settings = get_settings()
    if not settings.mock_mode:
        return

    async with session_scope(settings=settings) as session:
        res = await session.execute(select(VCenter).where(VCenter.name == _MOCK_VC_NAME))
        if res.scalar_one_or_none() is not None:
            logger.info("MOCK_MODE seed skipped (already present): %s", _MOCK_VC_NAME)
            return

        vc = VCenter(
            name=_MOCK_VC_NAME,
            host="mock.vcenter.local",
            port=443,
            username="mock-user",
            password="mock-password",
            is_enabled=True,
        )
        session.add(vc)
        await session.flush()

        guides = (
            EventTypeGuide(
                event_type=_EVENT_TYPES[0],
                general_meaning="（モック）仮想マシンの電源投入イベントです。",
                typical_causes="（モック）管理者操作または自動化による起動。",
                remediation="（モック）意図した起動か確認する。",
                action_required=False,
            ),
            EventTypeGuide(
                event_type=_EVENT_TYPES[1],
                general_meaning="（モック）アラーム状態の変化です。",
                typical_causes="（モック）しきい値超過や状態遷移。",
                remediation="（モック）アラーム定義と対象オブジェクトを確認する。",
                action_required=True,
            ),
            EventTypeGuide(
                event_type=_EVENT_TYPES[2],
                general_meaning="（モック）ホストとの接続が失われたことを示します。",
                typical_causes="（モック）ネットワーク障害・ホスト停止・管理エージェント異常。",
                remediation="（モック）ホストの電源・ネットワーク・vpxa/hostd を確認する。",
                action_required=True,
            ),
        )
        for g in guides:
            session.add(g)

        now = datetime.now(timezone.utc)
        for i, et in enumerate(_EVENT_TYPES):
            session.add(
                EventRecord(
                    vcenter_id=vc.id,
                    occurred_at=now - timedelta(minutes=15 * (len(_EVENT_TYPES) - i)),
                    event_type=et,
                    message=f"（モック）シードイベント: {et}",
                    severity=("error" if i == 2 else "warning" if i == 1 else "info"),
                    entity_name="esxi-mock-01" if i == 2 else "vm-mock-web-01",
                    entity_type="HostSystem" if i == 2 else "VirtualMachine",
                    vmware_key=8_000_001 + i,
                    notable_score=10 + i * 20,
                ),
            )

        host_moid = "host-mock-01"
        ds_moid = "datastore-mock-01"
        for i in range(32):
            sampled = now - timedelta(minutes=2 * (31 - i))
            wobble = float(i)
            session.add(
                MetricSample(
                    vcenter_id=vc.id,
                    sampled_at=sampled,
                    entity_type="HostSystem",
                    entity_moid=host_moid,
                    entity_name="esxi-mock-01",
                    metric_key="host.cpu.usage_pct",
                    value=30.0 + wobble,
                ),
            )
            session.add(
                MetricSample(
                    vcenter_id=vc.id,
                    sampled_at=sampled,
                    entity_type="HostSystem",
                    entity_moid=host_moid,
                    entity_name="esxi-mock-01",
                    metric_key="host.mem.usage_pct",
                    value=40.0 + wobble * 0.5,
                ),
            )
            session.add(
                MetricSample(
                    vcenter_id=vc.id,
                    sampled_at=sampled,
                    entity_type="Datastore",
                    entity_moid=ds_moid,
                    entity_name="mock-datastore",
                    metric_key="datastore.space.used_bytes",
                    value=float(1_000_000_000_000 + i * 12_500_000),
                ),
            )

        existing_rule = await session.execute(
            select(AlertRule).where(AlertRule.name == "mock-demo-event-score")
        )
        if existing_rule.scalar_one_or_none() is None:
            session.add(
                AlertRule(
                    name="mock-demo-event-score",
                    rule_type="event_score",
                    is_enabled=True,
                    alert_level="warning",
                    config={"threshold": 40, "cooldown_minutes": 15},
                ),
            )

        logger.info("MOCK_MODE seed inserted demo data for %s", _MOCK_VC_NAME)
