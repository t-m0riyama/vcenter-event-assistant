"""保持期間と vCenter ごとの上限でログの台帳を整理する。"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.db.models import LogPattern, LogRecord
from vcenter_event_assistant.settings import Settings

_HAS_LOG = select(LogRecord.id).where(
    LogRecord.vcenter_id == LogPattern.vcenter_id,
    LogRecord.pattern_key == LogPattern.pattern_key,
).exists()


async def _purge_patterns(
    session: AsyncSession, cutoff: datetime, *, vcenter_id=None, limit: int | None = None,
) -> None:
    eligible = (LogPattern.last_seen_at < cutoff, ~_HAS_LOG)
    candidates = select(LogPattern.id).where(*eligible)
    if vcenter_id is not None:
        candidates = candidates.where(LogPattern.vcenter_id == vcenter_id)
    if limit is not None:
        candidates = candidates.order_by(LogPattern.last_seen_at, LogPattern.id).limit(limit)

    table = LogPattern.__table__
    if session.get_bind().dialect.name == "sqlite":
        await session.execute(table.delete().where(table.c.id.in_(candidates)))
        return

    # 並行取り込みが更新中の型は次の削除に回す。ロック後に別の文でログの有無を再確認する。
    ids = (await session.scalars(candidates.with_for_update(skip_locked=True))).all()
    for start in range(0, len(ids), 5_000):
        await session.execute(
            table.delete().where(table.c.id.in_(ids[start:start + 5_000]), *eligible)
        )


async def purge_old_log_patterns(session: AsyncSession, *, settings: Settings) -> None:
    """期限と上限を適用し、ログに残っている型を保護する。"""
    now = utcnow()
    if settings.log_pattern_retention_days:
        await _purge_patterns(session, now - timedelta(days=settings.log_pattern_retention_days))

    log_cutoff = now - timedelta(days=settings.log_retention_days)
    count = func.count(LogPattern.id)
    excesses = (await session.execute(
        select(LogPattern.vcenter_id, count - settings.log_pattern_max_per_vcenter)
        .group_by(LogPattern.vcenter_id)
        .having(count > settings.log_pattern_max_per_vcenter)
    )).all()
    for vcenter_id, excess in excesses:
        await _purge_patterns(session, log_cutoff, vcenter_id=vcenter_id, limit=excess)
