"""同じトランザクションで、保存済みのログを台帳に反映する。"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Row, case, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.auth.timeutil import as_utc
from vcenter_event_assistant.db.models import LogPattern, LogPatternBaseline, LogRecord
from vcenter_event_assistant.services.log_patterns.masking import MASK_VERSION, normalize_log_kind
from vcenter_event_assistant.services.log_patterns.severity import WARNING_RANK, severity_rank

LOG_PATTERN_RETURNING = (
    LogRecord.id, LogRecord.vcenter_id, LogRecord.pattern_key, LogRecord.log_kind,
    LogRecord.effective_at, LogRecord.severity, LogRecord.source_id,
)


@dataclass
class _PatternStats:
    first_seen_at: datetime
    last_seen_at: datetime
    total_count: int = 0
    max_severity_rank: int = 0
    warning_first_seen_at: datetime | None = None
    warning_first_source_id: str | None = None

    def add(self, at: datetime, rank: int, source_id: str) -> None:
        self.first_seen_at = min(self.first_seen_at, at)
        self.last_seen_at = max(self.last_seen_at, at)
        self.total_count += 1
        self.max_severity_rank = max(self.max_severity_rank, rank)
        if rank >= WARNING_RANK and (self.warning_first_seen_at is None or at < self.warning_first_seen_at):
            self.warning_first_seen_at = at
            self.warning_first_source_id = source_id


async def update_ledger(
    session: AsyncSession,
    logs: Iterable[Row[Any] | LogRecord],
    templates: dict[str, str],
    *,
    started_at: datetime,
) -> None:
    """挿入・更新できた行だけを集め、キーの順に台帳と開始の行を入れる。"""
    grouped: dict[tuple[UUID, str], tuple[str, _PatternStats]] = {}
    sources: set[tuple[UUID, str, str]] = set()
    for log in logs:
        at = as_utc(log.effective_at)
        kind = normalize_log_kind(log.log_kind)
        assert log.pattern_key is not None
        group_key = (log.vcenter_id, log.pattern_key)
        if group_key not in grouped:
            grouped[group_key] = (kind, _PatternStats(at, at))
        grouped[group_key][1].add(at, severity_rank(log.severity), log.source_id)
        sources.add((log.vcenter_id, log.source_id, kind))

    if not grouped:
        return
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    pattern = LogPattern.__table__.c
    stmt = insert(LogPattern)
    incoming = stmt.excluded
    earlier_warning = incoming.warning_first_seen_at.is_not(None) & or_(
        pattern.warning_first_seen_at.is_(None),
        incoming.warning_first_seen_at < pattern.warning_first_seen_at,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["vcenter_id", "pattern_key"],
        set_={
            "first_seen_at": case(
                (incoming.first_seen_at < pattern.first_seen_at, incoming.first_seen_at),
                else_=pattern.first_seen_at,
            ),
            "last_seen_at": case(
                (incoming.last_seen_at > pattern.last_seen_at, incoming.last_seen_at),
                else_=pattern.last_seen_at,
            ),
            "total_count": pattern.total_count + incoming.total_count,
            "max_severity_rank": case(
                (incoming.max_severity_rank > pattern.max_severity_rank, incoming.max_severity_rank),
                else_=pattern.max_severity_rank,
            ),
            "warning_first_seen_at": case(
                (earlier_warning, incoming.warning_first_seen_at),
                else_=func.coalesce(pattern.warning_first_seen_at, incoming.warning_first_seen_at),
            ),
            "warning_first_source_id": case(
                (earlier_warning, incoming.warning_first_source_id),
                else_=pattern.warning_first_source_id,
            ),
        },
    )
    await session.execute(stmt, [
        {
            "vcenter_id": vcenter_id,
            "pattern_key": key,
            "pattern_version": MASK_VERSION,
            "log_kind": kind,
            "template": templates[key],
            **vars(stats),
        }
        for (vcenter_id, key), (kind, stats) in sorted(grouped.items())
    ])

    baseline = insert(LogPatternBaseline).on_conflict_do_nothing(
        index_elements=["vcenter_id", "source_id", "log_kind", "pattern_version"],
    )
    await session.execute(baseline, [
        {
            "vcenter_id": vcenter_id,
            "source_id": source_id,
            "log_kind": kind,
            "pattern_version": MASK_VERSION,
            "started_at": started_at,
        }
        for vcenter_id, source_id, kind in sorted(sources)
    ])


def is_past_warmup(
    warning_first_seen_at: datetime | None,
    started_at: datetime | None,
    completed_at: datetime | None,
    warmup_days: int,
) -> bool:
    """今の版の埋め戻しと、出どころごとの慣らしが済んだかを判定する。"""
    return (
        completed_at is not None
        and started_at is not None
        and warning_first_seen_at is not None
        and as_utc(warning_first_seen_at) >= as_utc(started_at) + timedelta(days=warmup_days)
    )
