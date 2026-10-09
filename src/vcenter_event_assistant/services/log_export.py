"""Bounded-memory CSV export using short-lived, keyset-paged DB reads."""

import asyncio
import csv
import io
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy import func, select, tuple_
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.db.models import LogRecord, VCenter

logger = logging.getLogger(__name__)
BATCH_SIZE = 2000
CHUNK_BYTES = 64 * 1024
HEADER = (
    "id",
    "vcenter_id",
    "vcenter_name",
    "source_id",
    "host",
    "log_kind",
    "effective_at",
    "occurred_at",
    "collected_at",
    "severity",
    "message",
    "file_generation",
    "byte_offset",
    "time_zone",
    "utc_offset",
)

# ログの内容など外部から入り得る文字列の列。時刻・オフセット・数値など、
# アプリが組み立てる列は含めない（``utc_offset`` の ``-04:00`` を壊さないため）。
_TEXT_COLUMNS = (
    "vcenter_name",
    "source_id",
    "host",
    "log_kind",
    "severity",
    "message",
    "file_generation",
)
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralize_csv_formula(value: str) -> str:
    """表計算ソフトが式として評価する先頭文字なら ``'`` を前置する（OWASP CSV Injection）。"""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


async def read_log_batch(
    factory: async_sessionmaker[AsyncSession],
    conditions: Sequence,
    upper_id: int,
    cursor: tuple[datetime, int] | None = None,
) -> list[RowMapping]:
    predicates = [*conditions, LogRecord.id <= upper_id]
    if cursor is not None:
        time, row_id = cursor
        predicates.append(
            tuple_(LogRecord.effective_at, LogRecord.id) < tuple_(time, row_id)
        )
    # Use scalar columns; no ORM identity map or lazy relationship reads.
    query = (
        select(*LogRecord.__table__.columns, VCenter.name.label("vcenter_name"))
        .outerjoin(VCenter, LogRecord.vcenter_id == VCenter.id)
        .where(*predicates)
        .order_by(LogRecord.effective_at.desc(), LogRecord.id.desc())
        .limit(BATCH_SIZE)
    )
    async with factory() as session:
        return list((await session.execute(query)).mappings())


async def prepare_log_export(
    factory: async_sessionmaker[AsyncSession],
    conditions: Sequence,
) -> tuple[int, list[RowMapping]]:
    async with factory() as session:
        upper_id = (
            await session.execute(select(func.max(LogRecord.id)))
        ).scalar_one() or 0
    return upper_id, await read_log_batch(factory, conditions, upper_id)


def csv_row(row: RowMapping, zone: ZoneInfo) -> str:
    fields = dict(row)
    fields["vcenter_name"] = fields["vcenter_name"] or str(fields["vcenter_id"])
    effective = to_utc(fields["effective_at"]).astimezone(zone)
    for key in ("effective_at", "occurred_at", "collected_at"):
        value = fields[key]
        fields[key] = (
            ""
            if value is None
            else to_utc(value)
            .astimezone(zone)
            .isoformat(sep=" ", timespec="seconds")[:19]
            .replace("-", "/")
        )
    seconds = int(effective.utcoffset().total_seconds())
    hours, remainder = divmod(abs(seconds), 3600)
    minutes, seconds_part = divmod(remainder, 60)
    fields["utc_offset"] = f"{'-' if seconds < 0 else '+'}{hours:02d}:{minutes:02d}"
    if seconds_part:
        fields["utc_offset"] += f":{seconds_part:02d}"
    fields["time_zone"] = zone.key
    for key in _TEXT_COLUMNS:
        if isinstance(fields[key], str):
            fields[key] = neutralize_csv_formula(fields[key])
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\r\n").writerow([fields[key] for key in HEADER])
    return output.getvalue()


async def stream_log_csv(
    factory: async_sessionmaker[AsyncSession],
    conditions: Sequence,
    zone: ZoneInfo,
    upper_id: int,
    first_batch: list[RowMapping],
    request: Request,
) -> AsyncIterator[bytes]:
    sent_rows = 0
    try:
        if await request.is_disconnected():
            return
        yield ("\ufeff" + ",".join(HEADER) + "\r\n").encode("utf-8")
        batch = first_batch
        # Do not retain the initial batch for the entire download.
        del first_batch
        while batch:
            if await request.is_disconnected():
                return
            chunk = bytearray()
            for row in batch:
                chunk.extend(csv_row(row, zone).encode("utf-8"))
                sent_rows += 1
                if len(chunk) >= CHUNK_BYTES:
                    if await request.is_disconnected():
                        return
                    yield bytes(chunk)
                    chunk.clear()
            if chunk:
                yield bytes(chunk)
            if len(batch) < BATCH_SIZE:
                break
            cursor = (batch[-1]["effective_at"], batch[-1]["id"])
            del batch
            if await request.is_disconnected():
                return
            batch = await read_log_batch(factory, conditions, upper_id, cursor)
    except asyncio.CancelledError:
        logger.info("Log CSV export cancelled after %s rows", sent_rows)
        raise
    except Exception:
        logger.exception("Log CSV export failed after %s rows", sent_rows)
        # Never turn a failed stream into a normally completed, partial CSV.
        raise
