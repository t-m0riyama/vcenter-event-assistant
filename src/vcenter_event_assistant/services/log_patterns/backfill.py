"""確定済みの id を境界に、ログの型を埋め戻して追いつく。"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import bindparam, case, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.db.models import LogPattern, LogPatternBackfillState, LogRecord, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.log_patterns.ledger import LOG_PATTERN_RETURNING, update_ledger
from vcenter_event_assistant.services.log_patterns.masking import MASK_VERSION, mask_message, pattern_key
from vcenter_event_assistant.settings import Settings

CHUNK_SIZE = 5_000
MAX_ROWS_PER_RUN = 50_000
_CONFIRMATION_DELAY = timedelta(seconds=270)
logger = logging.getLogger(__name__)
_run_lock = asyncio.Lock()


async def _lock_state(session: AsyncSession) -> LogPatternBackfillState:
    if session.get_bind().dialect.name == "sqlite":
        await session.execute(text("BEGIN IMMEDIATE"))
    return (await session.scalars(
        select(LogPatternBackfillState)
        .where(LogPatternBackfillState.pattern_version == MASK_VERSION)
        .with_for_update()
    )).one()


async def log_pattern_backfill(settings: Settings) -> None:
    """1 回分の埋め戻し、または完了後の追いつきを行う。"""
    async with _run_lock:
        try:
            await _backfill_once(settings)
        except Exception:
            logger.exception("log pattern backfill failed")
            raise


async def _backfill_once(settings: Settings) -> None:
    async with session_scope(settings=settings) as session:
        state = await _lock_state(session)
        current_max = await session.scalar(select(func.max(LogRecord.id))) or 0
        started_at = utcnow()
        pending = state.pending_upper_id
        recorded_at = state.pending_recorded_at
        if pending is None or recorded_at is None:
            state.pending_upper_id = current_max
            state.pending_recorded_at = started_at
            return
        can_confirm = started_at - as_utc(recorded_at) >= _CONFIRMATION_DELAY
        if state.upper_id is None:
            if not can_confirm:
                return
            state.upper_id = pending
        upper = state.upper_id
        cursor = state.last_id
        backfilling = state.completed_at is None

    bound = upper if backfilling else current_max
    read_count = 0
    while read_count < MAX_ROWS_PER_RUN:
        limit = min(CHUNK_SIZE, MAX_ROWS_PER_RUN - read_count)
        async with session_scope(settings=settings) as session:
            state = await _lock_state(session)
            # 別の実行が進めた境界を、この実行の古い値で上書きしない。
            if (
                state.pending_upper_id != pending
                or state.pending_recorded_at != recorded_at
                or (state.completed_at is None) != backfilling
                or (backfilling and state.last_id != cursor)
            ):
                return

            count, last_read_id = await _fill_chunk(
                session, cursor, bound, limit, started_at=started_at,
            )
            read_count += count
            cursor = last_read_id
            at_end = count < limit or cursor >= bound
            done = at_end or read_count >= MAX_ROWS_PER_RUN
            if backfilling:
                # 末尾の行が削除されていても、読める行をすべて読んだら完了する。
                state.last_id = upper if at_end else cursor
                if at_end:
                    state.completed_at = utcnow()
            elif done and can_confirm:
                # 今回見えた最大 id は次回まで確定しない。
                state.last_id = max(state.last_id, min(pending, cursor))

            if done:
                # 時刻も残し、早く再実行されたときは前の観測を引き継ぐ。
                if can_confirm:
                    state.pending_upper_id = current_max
                    state.pending_recorded_at = started_at
                if state.completed_at is not None:
                    await session.execute(
                        delete(LogPattern).where(LogPattern.pattern_version != MASK_VERSION)
                    )
                return


async def _fill_chunk(
    session: AsyncSession, after_id: int, through_id: int, limit: int, *, started_at: datetime,
) -> tuple[int, int]:
    needs_pattern = or_(
        LogRecord.pattern_key.is_(None),
        LogRecord.pattern_version.is_distinct_from(MASK_VERSION),
    )
    # 過去の孤児ログは台帳に入れず、走査だけを進める。
    has_vcenter = select(VCenter.id).where(VCenter.id == LogRecord.vcenter_id).exists()
    rows = (await session.execute(
        select(
            LogRecord.id, LogRecord.log_kind,
            case((needs_pattern, case((has_vcenter, LogRecord.message)))).label("message"),
        )
        .where(LogRecord.id > after_id, LogRecord.id <= through_id)
        .order_by(LogRecord.id)
        .limit(limit)
    )).all()

    update_log = (
        update(LogRecord.__table__)
        .where(LogRecord.id == bindparam("log_id"), needs_pattern)
        .values(pattern_key=bindparam("new_pattern_key"), pattern_version=MASK_VERSION)
        .returning(*LOG_PATTERN_RETURNING)
    )
    updated = []
    templates: dict[str, str] = {}
    for row_id, kind, message in rows:
        if message is None:
            continue
        template = mask_message(message)
        key = pattern_key(kind, template)
        result = await session.execute(update_log, {"log_id": row_id, "new_pattern_key": key})
        if (saved := result.one_or_none()) is not None:
            updated.append(saved)
            templates[key] = template
    await update_ledger(session, updated, templates, started_at=started_at)
    return len(rows), rows[-1].id if rows else after_id
