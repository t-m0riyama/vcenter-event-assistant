"""Exercise the real CSV generator against a disposable, empty database.

Default: a temporary SQLite database, deleted on exit. For PostgreSQL, supply
--database-url pointing to an EMPTY disposable database (never production).
"""

import argparse
import asyncio
import json
import resource
import sys
import tempfile
import time
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vcenter_event_assistant.db.models import Base, LogRecord, VCenter
from vcenter_event_assistant.services.log_export import (
    prepare_log_export,
    stream_log_csv,
)


class ConnectedRequest:
    async def is_disconnected(self):
        return False


def peak_mib():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / (1024**2 if sys.platform == "darwin" else 1024), 1)


async def benchmark(url, rows):
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
            if tables:
                raise RuntimeError("Benchmark requires an empty disposable database")
            await conn.run_sync(
                lambda c: Base.metadata.create_all(
                    c, tables=[VCenter.__table__, LogRecord.__table__]
                )
            )
            vc = uuid.uuid4()
            await conn.execute(
                VCenter.__table__.insert().values(
                    id=vc,
                    name="CSV benchmark",
                    host="vc.test",
                    username="u",
                    password="p",
                )
            )
            if engine.dialect.name == "sqlite":
                numbers = "WITH RECURSIVE seq(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM seq WHERE i < :rows)"
                from_sql = "FROM seq"
                timestamp = "datetime('2026-10-03 00:00:00', '-' || CAST(i / 10 AS INTEGER) || ' seconds') || '.000000'"
                vc_value = vc.hex
            else:
                numbers = ""
                from_sql = "FROM generate_series(1, :rows) AS seq(i)"
                timestamp = (
                    "TIMESTAMP '2026-10-03 00:00:00' - (i / 10) * INTERVAL '1 second'"
                )
                vc_value = str(vc)
            started = time.perf_counter()
            await conn.execute(
                text(f"""{numbers}
                INSERT INTO log_records
                (vcenter_id, collector_id, source_id, host, log_kind, file_generation,
                 byte_offset, effective_at, collected_at, severity, message)
                SELECT :vc, 'test', 'esxi-1', 'esxi.test', 'vmkernel', 'one', i,
                       {timestamp}, {timestamp}, 'error', '日本語, "ERROR"\n stack trace'
                {from_sql}
                """),
                {"rows": rows, "vc": vc_value},
            )
        print(
            json.dumps(
                {
                    "stage": "seeded",
                    "dialect": engine.dialect.name,
                    "rows": rows,
                    "seconds": round(time.perf_counter() - started, 2),
                    "peak_mib": peak_mib(),
                }
            ),
            flush=True,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        started = time.perf_counter()
        upper, first = await prepare_log_export(factory, [])
        size = 0
        line_count = 0
        sample_at = 100_000
        probe_max_ms = 0
        baseline_mib = None
        stream = stream_log_csv(
            factory, [], ZoneInfo("Asia/Tokyo"), upper, first, ConnectedRequest()
        )
        del first
        async for chunk in stream:
            size += len(chunk)
            # Fixture messages contain LF, so CRLF counts CSV record endings.
            line_count += chunk.count(b"\r\n")
            if size >= sample_at:
                async with factory() as session:
                    probe_start = time.perf_counter()
                    assert (
                        await session.execute(select(func.max(LogRecord.id)))
                    ).scalar_one() == rows
                    probe_max_ms = max(
                        probe_max_ms, (time.perf_counter() - probe_start) * 1000
                    )
                if baseline_mib is None:
                    baseline_mib = peak_mib()
                print(
                    json.dumps(
                        {"stage": "stream", "bytes": size, "peak_mib": peak_mib()}
                    ),
                    flush=True,
                )
                sample_at = size + 100 * 1024 * 1024
        assert line_count == rows + 1
        print(
            json.dumps(
                {
                    "stage": "done",
                    "dialect": engine.dialect.name,
                    "rows": rows,
                    "bytes": size,
                    "seconds": round(time.perf_counter() - started, 2),
                    "baseline_mib": baseline_mib,
                    "peak_mib": peak_mib(),
                    "probe_max_ms": round(probe_max_ms, 2),
                }
            ),
            flush=True,
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=2_000_000)
    parser.add_argument("--database-url")
    args = parser.parse_args()
    if args.rows < 1:
        parser.error("--rows must be positive")
    if args.database_url:
        asyncio.run(benchmark(args.database_url, args.rows))
    else:
        with tempfile.TemporaryDirectory(prefix="vea-csv-benchmark-") as directory:
            url = f"sqlite+aiosqlite:///{Path(directory) / 'benchmark.db'}"
            asyncio.run(benchmark(url, args.rows))
