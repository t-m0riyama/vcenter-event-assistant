"""
``MOCK_MODE=1`` 時のデモ用 DB シード。

投入内容: デモ vCenter・イベント種別ガイド・イベント・ホスト／Datastore メトリクス・
簡易アラートルール。同一 vCenter 名が既にあれば何もしない（冪等）。
ガイドの ``event_type`` は本番データと衝突しない ``MockDemo*`` 名を使う。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from vcenter_event_assistant.db.models import (
    AlertRule,
    EventEntity,
    EventRecord,
    EventTypeGuide,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.mocks.mock_collectors import MOCK_HOST_MOID, MOCK_VM_MOID
from vcenter_event_assistant.rules.notable import final_notable_score
from vcenter_event_assistant.settings_binding import require_settings

logger = logging.getLogger(__name__)

_MOCK_VC_NAME = "mock-demo-vc"
# 実環境の event_type_guides と衝突しないデモ専用名
_EVENT_TYPES = (
    "vim.event.MockDemoVmPoweredOnEvent",
    "vim.event.MockDemoAlarmStatusChangedEvent",
    "vim.event.MockDemoHostConnectionLostEvent",
)


async def run_mock_mode_seed_if_enabled() -> None:
    """``settings.mock_mode`` のとき、未シードならデモデータを挿入する。"""
    settings = require_settings()
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

        meanings = (
            "（モック）仮想マシンの電源投入イベントです。",
            "（モック）アラーム状態の変化です。",
            "（モック）ホストとの接続が失われたことを示します。",
        )
        causes = (
            "（モック）管理者操作または自動化による起動。",
            "（モック）しきい値超過や状態遷移。",
            "（モック）ネットワーク障害・ホスト停止・管理エージェント異常。",
        )
        remediations = (
            "（モック）意図した起動か確認する。",
            "（モック）アラーム定義と対象オブジェクトを確認する。",
            "（モック）ホストの電源・ネットワーク・vpxa/hostd を確認する。",
        )
        for i, et in enumerate(_EVENT_TYPES):
            existing_guide = await session.execute(
                select(EventTypeGuide).where(EventTypeGuide.event_type == et)
            )
            if existing_guide.scalar_one_or_none() is not None:
                continue
            session.add(
                EventTypeGuide(
                    event_type=et,
                    general_meaning=meanings[i],
                    typical_causes=causes[i],
                    remediation=remediations[i],
                    action_required=(i > 0),
                ),
            )

        now = datetime.now(timezone.utc)
        events = (
            (45, _EVENT_TYPES[0], False, "info", 10),
            (30, _EVENT_TYPES[1], False, "warning", 30),
            (15, _EVENT_TYPES[2], True, "error", 50),
            *((minutes, "vim.event.HostConnectionLostEvent", True, "info", None) for minutes in (12, 8, 4)),
        )
        for i, (minutes, et, is_host, severity, score) in enumerate(events):
            message = f"（モック）シードイベント: {et}"
            if score is None:
                message = "（モック）ホストと vCenter の接続が切れました。"
                score = final_notable_score(event_type=et, severity=severity, message=message)
            entity_name = "esxi-mock-01" if is_host else "vm-mock-web-01"
            entity_type = "HostSystem" if is_host else "VirtualMachine"
            entity_moid = MOCK_HOST_MOID if is_host else MOCK_VM_MOID
            session.add(
                EventRecord(
                    vcenter_id=vc.id,
                    occurred_at=now - timedelta(minutes=minutes),
                    event_type=et,
                    message=message,
                    severity=severity,
                    entity_name=entity_name,
                    entity_type=entity_type,
                    entity_moid=entity_moid,
                    entities=[EventEntity(
                        vcenter_id=vc.id,
                        role="host" if is_host else "vm",
                        position=0,
                        is_primary=True,
                        entity_name=entity_name,
                        entity_type=entity_type,
                        entity_moid=entity_moid,
                    )],
                    vmware_key=8_000_001 + i,
                    notable_score=score,
                ),
            )

        ds_moid = "datastore-mock-01"
        for i in range(32):
            sampled = now - timedelta(minutes=2 * (31 - i))
            wobble = float(i)
            session.add(
                MetricSample(
                    vcenter_id=vc.id,
                    sampled_at=sampled,
                    entity_type="HostSystem",
                    entity_moid=MOCK_HOST_MOID,
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
                    entity_moid=MOCK_HOST_MOID,
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
                    metric_key="datastore.space.used_pct",
                    value=55.0 + wobble * 0.25,
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

        for rule in (
            AlertRule(
                name="mock-demo-event-score",
                rule_type="event_score",
                is_enabled=True,
                alert_level="warning",
                config={"threshold": 40, "cooldown_minutes": 15},
            ),
            AlertRule(
                name="mock-demo-event-pattern",
                rule_type="event_pattern",
                is_enabled=True,
                alert_level="error",
                config={"pattern_ids": ["host-conn-flapping"], "cooldown_minutes": 10},
            ),
        ):
            existing_id = await session.scalar(select(AlertRule.id).where(AlertRule.name == rule.name))
            if existing_id is None:
                session.add(rule)

        logger.info("MOCK_MODE seed inserted demo data for %s", _MOCK_VC_NAME)
