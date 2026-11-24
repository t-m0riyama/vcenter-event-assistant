"""通知履歴を読み取り、通知時点の対象を解決する。"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import AlertHistory
from vcenter_event_assistant.services.alerting.alert_entity_resolution import (
    EventPatternEntityKey,
    MetricProbe,
    ResolvedEntity,
    collect_metric_probes,
    metric_name_lookback,
    metric_probe,
    resolve_event_pattern_entities,
    resolve_metric_entities_at,
)
from vcenter_event_assistant.services.alerting.alert_eval_common import parse_event_pattern_context_key


@dataclass(frozen=True)
class AlertHistoryTarget:
    vcenter_id: uuid.UUID | None
    entity_moid: str | None
    entity_name: str | None


async def _resolve_history_entities(
    session: AsyncSession, items: list[AlertHistory], perf_sample_interval_seconds: int
) -> dict[MetricProbe, ResolvedEntity]:
    """ページ内の metric_threshold 行の対象名を、タイムラインと同じ関数でまとめて引く（N+1 にしない）。

    名前は行ごとに「その行のルールの指標の、``occurred_at`` の時点の名前」。ページの区切りや同じページに
    居合わせるほかの行に依存しないので、行の「タイムラインで見る」リンク（``occurred_at`` の前後・
    ``entity_name`` で絞る）で開いたタイムラインにも同じ名前で出る。1 ページ（最大 200 件）は 1 本の問い合わせで
    引ける（ルールに ``metric_key`` が無い古い行が混じるときだけ 2 本）。
    """
    probes = collect_metric_probes(
        (
            item.rule.rule_type if item.rule else "",
            item.context_key,
            item.rule.config if item.rule else None,
            item.occurred_at,
        )
        for item in items
    )
    return await resolve_metric_entities_at(
        session, probes, lookback=metric_name_lookback(perf_sample_interval_seconds)
    )


def _history_target(
    item: AlertHistory,
    entities: Mapping[MetricProbe, ResolvedEntity],
    pattern_entities: Mapping[EventPatternEntityKey, ResolvedEntity],
) -> AlertHistoryTarget:
    rule_type = item.rule.rule_type if item.rule else ""
    vcenter_id: uuid.UUID | None = None
    entity_moid: str | None = None
    entity_name: str | None = None
    if rule_type == "metric_threshold":
        probe = metric_probe(item.context_key, item.rule.config if item.rule else None, item.occurred_at)
        if probe is not None:
            vcenter_id, entity_moid, _, _ = probe
            hit = entities.get(probe)
            entity_name = hit.name if hit is not None else None
    elif rule_type == "event_pattern":
        parsed = parse_event_pattern_context_key(item.context_key)
        if parsed is not None:
            vcenter_id, entity_moid, _ = parsed
            hit = pattern_entities.get((vcenter_id, entity_moid))
            entity_name = hit.name if hit is not None else None
    return AlertHistoryTarget(vcenter_id, entity_moid, entity_name)


async def resolve_alert_history_targets(
    session: AsyncSession, items: list[AlertHistory], perf_sample_interval_seconds: int,
) -> dict[int, AlertHistoryTarget]:
    entities = await _resolve_history_entities(session, items, perf_sample_interval_seconds)
    pattern_entities = await resolve_event_pattern_entities(
        session, (item.context_key for item in items if item.rule and item.rule.rule_type == "event_pattern"),
    )
    return {item.id: _history_target(item, entities, pattern_entities) for item in items}
