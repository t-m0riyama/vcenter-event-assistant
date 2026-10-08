"""インシデントタイムラインスナップショットの永続化ヘルパー。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.schemas.chat import IncidentTimelineBuildRequest
from vcenter_event_assistant.db.models import AlertRule, AlertState, IncidentTimelineManualSnapshot

_CONTEXT_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug_alert_context_key(context_key: str) -> str:
    """AlertState.context_key を trigger_id 用の snake_case 断片に正規化する。"""
    slug = _CONTEXT_SLUG_RE.sub("_", context_key.lower()).strip("_")
    return slug or "unknown"


def format_alert_rule_trigger_id(*, rule_id: int, context_key: str) -> str:
    """AlertRule 発火スナップショット用の trigger_id を生成する。"""
    return f"alert_rule_{rule_id}_{slug_alert_context_key(context_key)}"


def build_alert_rule_snapshot_build_request(
    *,
    fired_at: datetime,
    to_time: datetime,
    lookback_hours: int,
) -> IncidentTimelineBuildRequest:
    """firing 時点から再生成可能な build_request を組み立てる。"""
    return IncidentTimelineBuildRequest(
        from_time=fired_at - timedelta(hours=lookback_hours),
        to_time=to_time,
        include_period_metrics_cpu=True,
        include_period_metrics_memory=True,
        alert_top_n=7,
        top_notable_min_score=1,
    )


async def persist_alert_rule_firing_snapshot(
    *,
    session: AsyncSession,
    rule: AlertRule,
    state: AlertState,
    details: str,
    to_time: datetime,
    lookback_hours: int,
) -> None:
    """AlertRule の firing 時に auto スナップショットを 1 件保存する（重複はスキップ）。"""
    if state.state != "firing":
        return

    fired_at = state.fired_at
    if fired_at.tzinfo is None:
        fired_at = fired_at.replace(tzinfo=timezone.utc)

    build_body = build_alert_rule_snapshot_build_request(
        fired_at=fired_at,
        to_time=to_time,
        lookback_hours=lookback_hours,
    )
    trigger_id = format_alert_rule_trigger_id(rule_id=rule.id, context_key=state.context_key)
    normalized_timestamp = fired_at.astimezone(timezone.utc)

    exists = await session.execute(
        select(IncidentTimelineManualSnapshot.id).where(
            and_(
                IncidentTimelineManualSnapshot.snapshot_kind == "auto",
                IncidentTimelineManualSnapshot.from_time == build_body.from_time,
                IncidentTimelineManualSnapshot.to_time == build_body.to_time,
                IncidentTimelineManualSnapshot.timestamp_utc == normalized_timestamp,
                IncidentTimelineManualSnapshot.trigger_id == trigger_id,
            )
        )
    )
    if exists.scalar_one_or_none() is not None:
        return

    session.add(
        IncidentTimelineManualSnapshot(
            from_time=build_body.from_time,
            to_time=build_body.to_time,
            timestamp_utc=normalized_timestamp,
            operator_note=f"自動スナップショット: {rule.name} ({state.context_key})",
            build_request_payload=build_body.model_dump(mode="json", by_alias=True, exclude_none=True),
            snapshot_kind="auto",
            trigger_id=trigger_id,
            trigger_evidence={
                "trigger_type": "alert_rule",
                "rule_id": rule.id,
                "rule_name": rule.name,
                "context_key": state.context_key,
                "state": state.state,
                "fired_at_utc": normalized_timestamp.isoformat().replace("+00:00", "Z"),
                "details": details,
            },
        )
    )
