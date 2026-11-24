"""タイムラインの期間に初めて警告以上で出たログの型を調べる。"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.api.schemas.incident_timeline_view import (
    IncidentTimelineHighlights,
    IncidentTimelineLogPatternWarmup,
    IncidentTimelineNewLogPattern,
)
from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.db.models import (
    LogPattern,
    LogPatternBackfillState,
    LogPatternBaseline,
    LogRecord,
    VCenter,
)
from vcenter_event_assistant.services.alerting.alert_entity_resolution import chunks
from vcenter_event_assistant.services.log_patterns.ledger import is_past_warmup
from vcenter_event_assistant.services.log_patterns.masking import MASK_VERSION, UNPARSED
from vcenter_event_assistant.services.log_patterns.normalization import normalized_text_sql
from vcenter_event_assistant.services.log_patterns.severity import WARNING_SEVERITIES, severity_rank_sql
from vcenter_event_assistant.settings_binding import require_settings

_PATTERN_BATCH_SIZE = 500
_NEW_LOG_PATTERNS_LIMIT = 10
_WARMUPS_LIMIT = 20
_HOSTS_LIMIT = 3


@dataclass
class _WarningStats:
    count: int
    first_utc: datetime
    max_rank: int
    hosts: list[str] = field(default_factory=list)


def pick_new_log_patterns(
    patterns: Iterable[IncidentTimelineNewLogPattern],
) -> list[IncidentTimelineNewLogPattern]:
    """重大度、期間内の最初の時刻、キーの順に並べ、上位の型を返す。"""
    return sorted(
        patterns, key=lambda p: (-p.max_severity_rank, p.first_utc, p.pattern_key, p.vcenter_id)
    )[:_NEW_LOG_PATTERNS_LIMIT]


async def collect_new_log_patterns(
    session: AsyncSession,
    highlights: IncidentTimelineHighlights,
    log_filters: Sequence[ColumnElement[bool]],
    *,
    from_utc: datetime,
    to_utc: datetime,
    vcenter_id: UUID | None,
) -> None:
    """台帳で初出を判定し、対象に合う警告以上の行を数える。"""
    settings = require_settings()
    highlights.new_log_patterns = []
    completed_at = await session.scalar(
        select(LogPatternBackfillState.completed_at).where(LogPatternBackfillState.pattern_version == MASK_VERSION)
    )
    if completed_at is None:
        highlights.log_patterns_backfill_pending = True
        return
    highlights.new_log_patterns_out_of_retention = from_utc < utcnow() - timedelta(days=settings.log_retention_days)

    query = (
        select(LogPattern, VCenter.name, LogPatternBaseline.started_at)
        .join(VCenter, VCenter.id == LogPattern.vcenter_id)
        .outerjoin(LogPatternBaseline, and_(
            LogPatternBaseline.vcenter_id == LogPattern.vcenter_id,
            LogPatternBaseline.source_id == LogPattern.warning_first_source_id,
            LogPatternBaseline.log_kind == LogPattern.log_kind,
            LogPatternBaseline.pattern_version == LogPattern.pattern_version,
        ))
        .where(
            LogPattern.pattern_version == MASK_VERSION,
            LogPattern.warning_first_seen_at >= from_utc,
            LogPattern.warning_first_seen_at < to_utc,
            LogPattern.template != UNPARSED,
        )
        .order_by(LogPattern.vcenter_id, LogPattern.pattern_key)
    )
    if vcenter_id is not None:
        query = query.where(LogPattern.vcenter_id == vcenter_id)
    ready: list[tuple[LogPattern, str, datetime]] = []
    warming: list[tuple[LogPattern, str, datetime | None]] = []
    for pattern, name, started in (await session.execute(query)).tuples():
        warning_first = pattern.warning_first_seen_at
        if warning_first is None:
            continue
        if is_past_warmup(warning_first, started, completed_at, settings.log_pattern_warmup_days):
            ready.append((pattern, name, warning_first))
        else:
            warming.append((pattern, name, started))

    dialect = session.get_bind().dialect.name
    severity = normalized_text_sql(LogRecord.severity, dialect)
    filters = [
        *log_filters, LogRecord.pattern_version == MASK_VERSION, severity.in_(sorted(WARNING_SEVERITIES)),
    ]
    ranked: list[IncidentTimelineNewLogPattern] = []
    for batch in chunks(ready, _PATTERN_BATCH_SIZE):
        pairs = [(pattern.vcenter_id, pattern.pattern_key) for pattern, _, _ in batch]
        counts = await _warning_counts(session, filters, pairs)
        for pattern, name, warning_first in batch:
            stats = counts.get((pattern.vcenter_id, pattern.pattern_key))
            if stats is not None:
                ranked.append(IncidentTimelineNewLogPattern(
                    vcenter_id=pattern.vcenter_id, vcenter_name=name, pattern_key=pattern.pattern_key,
                    log_kind=pattern.log_kind, template=pattern.template, count=stats.count,
                    first_utc=stats.first_utc, max_severity_rank=stats.max_rank, hosts=stats.hosts,
                    first_seen_at=pattern.first_seen_at, warning_first_seen_at=warning_first,
                ))

    highlights.new_log_patterns = pick_new_log_patterns(ranked)
    highlights.new_log_patterns_total = len(ranked)
    warmups = await _warmup_sources(
        session, filters, warming, warmup_days=settings.log_pattern_warmup_days,
    )
    highlights.log_patterns_warming_up_total = len(warmups)
    highlights.log_patterns_warming_up = warmups[:_WARMUPS_LIMIT]


async def _warmup_sources(
    session: AsyncSession,
    filters: Sequence[ColumnElement[bool]],
    warming: Sequence[tuple[LogPattern, str, datetime | None]],
    *,
    warmup_days: int,
) -> list[IncidentTimelineLogPatternWarmup]:
    """絞り込みに合う行があった型から、判定を見送った出どころを取り出す。"""
    warmup = timedelta(days=warmup_days)
    warmups: dict[tuple[UUID, str | None, str], IncidentTimelineLogPatternWarmup] = {}
    pair = (LogRecord.vcenter_id, LogRecord.pattern_key)
    for batch in chunks(warming, _PATTERN_BATCH_SIZE):
        query = (
            select(
                *pair,
                func.min(LogRecord.host).filter(LogRecord.source_id == LogPattern.warning_first_source_id),
            )
            .select_from(LogRecord)
            .join(LogPattern, and_(
                LogPattern.vcenter_id == LogRecord.vcenter_id,
                LogPattern.pattern_key == LogRecord.pattern_key,
                LogPattern.pattern_version == MASK_VERSION,
            ))
            .where(*filters, tuple_(*pair).in_([
                (pattern.vcenter_id, pattern.pattern_key) for pattern, _, _ in batch
            ]))
            .group_by(*pair)
        )
        hosts = {(vc, key): host for vc, key, host in (await session.execute(query)).tuples()}
        for pattern, name, started in batch:
            match = (pattern.vcenter_id, pattern.pattern_key)
            if match not in hosts:
                continue
            key = (pattern.vcenter_id, pattern.warning_first_source_id, pattern.log_kind)
            if key not in warmups or warmups[key].host is None:
                warmups[key] = IncidentTimelineLogPatternWarmup(
                    vcenter_id=pattern.vcenter_id, vcenter_name=name, source_id=pattern.warning_first_source_id,
                    host=hosts[match], log_kind=pattern.log_kind,
                    warmup_ends_at=as_utc(started) + warmup if started is not None else None,
                )
    return sorted(
        warmups.values(), key=lambda w: (w.vcenter_name, w.vcenter_id, w.source_id or "", w.log_kind)
    )


async def _warning_counts(
    session: AsyncSession,
    filters: Sequence[ColumnElement[bool]],
    pairs: Sequence[tuple[UUID, str]],
) -> dict[tuple[UUID, str], _WarningStats]:
    dialect = session.get_bind().dialect.name
    host = LogRecord.host.collate("C") if dialect == "postgresql" else LogRecord.host
    by_host = (
        select(
            LogRecord.vcenter_id,
            LogRecord.pattern_key,
            host.label("host"),
            func.count().label("row_count"),
            func.min(LogRecord.effective_at).label("first_utc"),
            func.max(severity_rank_sql(normalized_text_sql(LogRecord.severity, dialect))).label("max_rank"),
        )
        .where(*filters, tuple_(LogRecord.vcenter_id, LogRecord.pattern_key).in_(pairs))
        .group_by(LogRecord.vcenter_id, LogRecord.pattern_key, host)
        .subquery()
    )
    # 型ごとの件数はすべてのホストを数え、応答には名前順で最大 3 つだけを載せる。
    partition = (by_host.c.vcenter_id, by_host.c.pattern_key)
    ordered = select(
        *partition,
        func.sum(by_host.c.row_count).over(partition_by=partition).label("row_count"),
        func.min(by_host.c.first_utc).over(partition_by=partition).label("first_utc"),
        func.max(by_host.c.max_rank).over(partition_by=partition).label("max_rank"),
        by_host.c.host,
        func.row_number().over(partition_by=partition, order_by=by_host.c.host).label("host_number"),
    ).subquery()
    query = select(
        ordered.c.vcenter_id, ordered.c.pattern_key, ordered.c.row_count, ordered.c.first_utc,
        ordered.c.max_rank, ordered.c.host,
    ).where(ordered.c.host_number <= _HOSTS_LIMIT).order_by(ordered.c.host_number)
    counts: dict[tuple[UUID, str], _WarningStats] = {}
    for vc, key, count, first, rank, host_name in (await session.execute(query)).tuples():
        if key is None:
            continue
        pair = (vc, key)
        if pair not in counts:
            counts[pair] = _WarningStats(count, first, rank)
        counts[pair].hosts.append(host_name)
    return counts
