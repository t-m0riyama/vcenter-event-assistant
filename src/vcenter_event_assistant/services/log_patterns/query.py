"""期間内のログを型ごとに集計する。"""

from collections.abc import Sequence

from sqlalchemy import and_, case, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.api.schemas.log_patterns import LogPatternRead, LogPatternsResponse
from vcenter_event_assistant.db.models import LogPattern, LogRecord, VCenter
from vcenter_event_assistant.services.log_patterns.masking import MASK_VERSION
from vcenter_event_assistant.services.log_patterns.normalization import normalized_text_sql
from vcenter_event_assistant.services.log_patterns.severity import severity_rank_sql

_GROUP_LIMIT = 200


class LogPatternScanLimitExceeded(Exception):
    """条件に合うログの行数が集計上限を超えた。"""


async def aggregate_log_patterns(
    session: AsyncSession, conditions: Sequence[ColumnElement[bool]], *, max_rows: int,
) -> LogPatternsResponse:
    dialect = session.get_bind().dialect.name
    matched = select(
        LogRecord.vcenter_id,
        case((LogRecord.pattern_version == MASK_VERSION, LogRecord.pattern_key)).label("pattern_key"),
        LogRecord.effective_at,
        LogRecord.severity,
    ).where(*conditions).limit(max_rows + 1).cte("matched")
    scanned = select(func.count()).select_from(matched).scalar_subquery()
    severity = severity_rank_sql(normalized_text_sql(matched.c.severity, dialect))
    # 行数の判定と集計を同じ SQL 文で行い、並行する取り込みの影響を受けないようにする。
    grouped = select(
        matched.c.vcenter_id,
        matched.c.pattern_key,
        func.count().label("row_count"),
        func.min(matched.c.effective_at).label("first_utc"),
        func.max(matched.c.effective_at).label("last_utc"),
        func.max(severity).label("max_severity_rank"),
    ).where(scanned <= max_rows).group_by(matched.c.vcenter_id, matched.c.pattern_key).subquery()
    # 総数と上位の型が同じ集計結果を参照できるようにする。
    patterns = select(
        grouped.c.vcenter_id,
        LogPattern.pattern_key,
        LogPattern.log_kind,
        LogPattern.template,
        LogPattern.first_seen_at,
        grouped.c.row_count,
        grouped.c.first_utc,
        grouped.c.last_utc,
        grouped.c.max_severity_rank,
    ).outerjoin(
        LogPattern,
        and_(
            LogPattern.vcenter_id == grouped.c.vcenter_id,
            LogPattern.pattern_key == grouped.c.pattern_key,
            LogPattern.pattern_version == MASK_VERSION,
        ),
    ).cte("patterns").prefix_with("MATERIALIZED")
    summary = select(
        scanned.label("scanned"),
        func.count(patterns.c.pattern_key).label("total"),
        func.coalesce(func.sum(patterns.c.row_count).filter(patterns.c.pattern_key.is_(None)), 0)
        .label("pending_count"),
    ).subquery()
    order = (patterns.c.row_count.desc(), patterns.c.pattern_key, patterns.c.vcenter_id)
    top = select(patterns).where(patterns.c.pattern_key.is_not(None)).order_by(*order).limit(_GROUP_LIMIT).subquery()
    rows = (await session.execute(
        select(summary, top, VCenter.name.label("vcenter_name"))
        .select_from(summary)
        .outerjoin(top, true())
        .outerjoin(VCenter, VCenter.id == top.c.vcenter_id)
        .order_by(top.c.row_count.desc(), top.c.pattern_key, top.c.vcenter_id)
    )).mappings().all()
    summary_row = rows[0]
    if summary_row["scanned"] > max_rows:
        raise LogPatternScanLimitExceeded
    total = summary_row["total"]
    return LogPatternsResponse(
        items=[
            LogPatternRead.model_validate(dict(row, count=row["row_count"]))
            for row in rows if row["pattern_key"] is not None
        ],
        total=total,
        truncated=total > _GROUP_LIMIT,
        pending_count=summary_row["pending_count"],
    )
