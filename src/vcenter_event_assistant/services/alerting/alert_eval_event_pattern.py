"""障害パターン型アラートルールの評価。"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from vcenter_event_assistant.alert_levels import alert_level_label_ja
from vcenter_event_assistant.db.models import AlertRule, AlertState, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_entity_resolution import resolve_event_pattern_entities
from vcenter_event_assistant.services.alerting.alert_eval_common import (
    AlertEvaluationDeps,
    as_utc,
    event_pattern_context_key,
    parse_event_pattern_context_key,
)
from vcenter_event_assistant.services.event_patterns.definitions import BUILTIN_PATTERNS
from vcenter_event_assistant.services.event_patterns.detection import PatternDetection
from vcenter_event_assistant.services.event_patterns.query import query_event_patterns

logger = logging.getLogger(__name__)


def _should_notify(state: AlertState, now: datetime, cooldown_minutes: int) -> bool:
    """新しい検知に限り呼び、解消済みかクールダウンを過ぎていれば通知する。"""
    return (
        state.state == "resolved"
        or state.last_notified_at is None
        or (now - as_utc(state.last_notified_at)).total_seconds() >= cooldown_minutes * 60
    )


def _details(
    detection: PatternDetection, vcenter_name: str | None, entity_name: str | None,
) -> str:
    pattern = detection.pattern
    entity = f"{entity_name} ({detection.entity_moid})" if entity_name else detection.entity_moid
    vcenter = f"{vcenter_name} ({detection.vcenter_id})" if vcenter_name else str(detection.vcenter_id)
    return "\n".join((
        f"パターン: {pattern.title} ({alert_level_label_ja(pattern.level)})",
        f"対象: {entity}",
        f"vCenter: {vcenter}",
        f"期間: {detection.first_utc.isoformat()} ～ {detection.last_utc.isoformat()}",
        f"件数: {len(detection.event_ids)}",
        f"説明: {pattern.description}",
    ))


async def evaluate_event_pattern_rule(
    deps: AlertEvaluationDeps, rule: AlertRule,
) -> tuple[int, int]:
    """検知の最新時刻を追い、発火・再通知・無通知の解消を保存する。"""
    pattern_ids = rule.config.get("pattern_ids", [])
    cooldown = rule.config.get("cooldown_minutes", 10)
    if (
        not isinstance(pattern_ids, list)
        or any(not isinstance(item, str) for item in pattern_ids)
        or type(cooldown) is not int
        or cooldown < 1
    ):
        logger.warning("event_pattern rule=%s id=%s: invalid config", rule.name, rule.id)
        return 0, 0

    requested = set(pattern_ids)
    patterns = [p for p in BUILTIN_PATTERNS if not requested or p.id in requested]
    selected = {p.id for p in patterns}
    for pattern_id in sorted(requested - selected):
        logger.warning("event_pattern rule=%s id=%s: unknown pattern %s", rule.name, rule.id, pattern_id)

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=deps.settings.alert_event_eval_lookback_hours)
    firings = resolutions = 0
    async with session_scope(settings=deps.settings) as session:
        detections, omitted = await query_event_patterns(
            session, window_start, now, vcenter_id=None, entity_moid=None, patterns=patterns,
        )
        for pattern_id in omitted:
            logger.warning("event_pattern rule=%s id=%s: row limit exceeded for %s", rule.name, rule.id, pattern_id)
        evaluated = selected.difference(omitted)

        latest: dict[str, PatternDetection] = {}
        for detection in detections:
            key = event_pattern_context_key(detection.vcenter_id, detection.entity_moid, detection.pattern.id)
            if key not in latest or detection.last_utc > latest[key].last_utc:
                latest[key] = detection

        states = {
            state.context_key: state
            for state in await session.scalars(select(AlertState).where(AlertState.rule_id == rule.id))
        }
        notifications: list[tuple[AlertState, PatternDetection]] = []
        for key, detection in latest.items():
            state = states.get(key)
            if state is None:
                state = AlertState(rule_id=rule.id, context_key=key)
                session.add(state)
            else:
                if detection.last_utc <= as_utc(state.fired_at):
                    continue
                if not _should_notify(state, now, cooldown):
                    state.fired_at = detection.last_utc
                    continue
            state.state = "firing"
            state.fired_at = detection.last_utc
            state.last_notified_at = now
            state.resolved_at = None
            notifications.append((state, detection))
            firings += 1

        for key, state in states.items():
            if state.state != "firing" or key in latest:
                continue
            parsed = parse_event_pattern_context_key(key)
            if parsed is None:
                continue
            pattern_id = parsed[2]
            if pattern_id in evaluated or (requested and pattern_id not in requested):
                state.state = "resolved"
                state.resolved_at = now
                resolutions += 1

        if notifications:
            vcenter_ids = {detection.vcenter_id for _, detection in notifications}
            rows = await session.execute(select(VCenter.id, VCenter.name).where(VCenter.id.in_(vcenter_ids)))
            names = {row.id: row.name for row in rows}
            entities = await resolve_event_pattern_entities(
                session, (state.context_key for state, _ in notifications),
            )
            for state, detection in notifications:
                entity = entities.get((detection.vcenter_id, detection.entity_moid))
                entity_name = entity.name if entity else detection.entity_name
                details = _details(detection, names.get(detection.vcenter_id), entity_name)
                deps.queue_notify(rule, state, {"details": details})
        await deps.persist_pending(session)

    return firings, resolutions
