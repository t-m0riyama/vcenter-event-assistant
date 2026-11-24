"""取り込み、埋め戻し、追いつきと保持を実際の DB で検証する。"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vcenter_event_assistant_plugin_api import CollectionBatch, CollectorManifest, LogRecordInput
from vcenter_event_assistant_plugin_api.testing import StubCollector
from vcenter_event_assistant.auth.timeutil import as_utc
from vcenter_event_assistant.db import session as db
from vcenter_event_assistant.db.models import (
    Base, LogPattern, LogPatternBackfillState, LogPatternBaseline, LogRecord, VCenter,
)
from vcenter_event_assistant.jobs.scheduler import purge_retention
from vcenter_event_assistant.plugins import runtime
from vcenter_event_assistant.plugins.config import CollectorConfig
from vcenter_event_assistant.plugins.registry import CollectorRegistration
from vcenter_event_assistant.plugins.runtime import run_collector_for_vcenter
from vcenter_event_assistant.services.log_patterns import backfill
from vcenter_event_assistant.services.log_patterns.ledger import is_past_warmup
from vcenter_event_assistant.services.log_patterns.masking import MASK_VERSION
from vcenter_event_assistant.settings import Settings

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)


@pytest.fixture(params=["sqlite", "postgres"])
async def ledger_db(request, monkeypatch):
    engine = admin = None
    if request.param == "postgres":
        url = os.environ.get("VEA_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("VEA_TEST_POSTGRES_URL must point to a dedicated test DB")
        schema = f"log_pattern_{uuid4().hex}"
        admin = create_async_engine(url)
        async with admin.begin() as conn:
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        monkeypatch.setattr(db, "_session_factory", async_sessionmaker(engine, expire_on_commit=False))
    try:
        if engine is not None:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        async with db.session_scope() as session:
            vc = VCenter(name="Test VC", host="vc.example", username="u", password="p")
            session.add(vc)
            await session.flush()
            if engine is not None:
                session.add(LogPatternBackfillState(pattern_version=MASK_VERSION, last_id=0))
        yield vc.id
    finally:
        if engine is not None:
            await engine.dispose()
        if admin is not None:
            async with admin.begin() as conn:
                await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            await admin.dispose()


@pytest.fixture
def backfill_clock(monkeypatch):
    now = NOW
    monkeypatch.setattr(backfill, "utcnow", lambda: now)

    def advance(seconds):
        nonlocal now
        now += timedelta(seconds=seconds)
        return now

    return advance


def log(offset, *, source="esx-1", at=NOW, severity=None, message="Path retried 12 times"):
    return LogRecordInput(source, source, "Hostd", "file", offset, at + timedelta(seconds=1),
                          message, occurred_at=at, severity=severity)


async def ingest(vc, *logs, collector="test.logs"):
    manifest = CollectorManifest(collector, "Logs", "1", data_kinds=frozenset({"log"}))
    plugin = StubCollector(manifest, batches=[CollectionBatch(logs=logs)])
    reg = CollectorRegistration(collector, plugin, "test", CollectorConfig(True, 60), "enabled")
    result = await run_collector_for_vcenter(Settings(), reg, vc)
    assert result.status == "ok"
    return result.logs_inserted


async def legacy(vc, *ids, version=None):
    async with db.session_scope() as session:
        session.add_all([
            LogRecord(id=row_id, vcenter_id=vc, source_id="legacy", host="esx",
                      collector_id="old.logs", log_kind=" Hostd ", file_generation="old",
                      byte_offset=row_id, effective_at=NOW, collected_at=NOW, severity="warn",
                      message="Path retried 42 times", pattern_version=version,
                      pattern_key="old" if version is not None else None)
            for row_id in ids
        ])


async def state():
    async with db.session_scope() as session:
        return (await session.scalars(select(LogPatternBackfillState))).one()


async def patterns():
    async with db.session_scope() as session:
        return (await session.scalars(select(LogPattern).order_by(LogPattern.id))).all()


async def obsolete_pattern(vc):
    async with db.session_scope() as session:
        session.add(LogPattern(
            vcenter_id=vc, pattern_key="old", pattern_version=2, log_kind="hostd",
            template="obsolete", first_seen_at=NOW, last_seen_at=NOW, total_count=1,
            max_severity_rank=1,
        ))


async def test_log_pattern_ingestion_ledger_and_utc(ledger_db):
    vc = ledger_db
    jst = timezone(timedelta(hours=9))
    row = log(0, at=NOW.astimezone(jst))
    before = datetime.now(timezone.utc)
    assert await ingest(vc, row, row) == 1
    assert await ingest(vc, row) == 0
    initial, = await patterns()
    assert (initial.total_count, initial.warning_first_seen_at, initial.warning_first_source_id) == (1, None, None)
    assert initial.template == "Path retried <N> times"
    assert initial.log_kind == "hostd"
    async with db.session_scope() as session:
        baseline = (await session.scalars(select(LogPatternBaseline))).one()
        saved = (await session.scalars(select(LogRecord))).one()
        assert as_utc(baseline.started_at) >= before
        assert as_utc(saved.occurred_at) == as_utc(saved.effective_at) == NOW
        assert as_utc(saved.collected_at) == NOW + timedelta(seconds=1)
        assert saved.pattern_key == initial.pattern_key and saved.pattern_version == MASK_VERSION
    assert await ingest(vc, log(1, source="esx-2", at=NOW + timedelta(hours=1), severity=" WaRn ")) == 1
    warning, = await patterns()
    assert as_utc(warning.warning_first_seen_at) == NOW + timedelta(hours=1)
    assert warning.warning_first_source_id == "esx-2"
    assert await ingest(
        vc,
        log(2, source="esx-3", at=NOW - timedelta(hours=1), severity=" CRIT ", message="Path retried 7 times"),
        log(3, at=NOW + timedelta(hours=2), severity="verbose"),
    ) == 2
    updated, = await patterns()
    assert updated.total_count == 4 and updated.max_severity_rank == 4
    assert as_utc(updated.first_seen_at) == as_utc(updated.warning_first_seen_at) == NOW - timedelta(hours=1)
    assert as_utc(updated.last_seen_at) == NOW + timedelta(hours=2)
    assert updated.warning_first_source_id == "esx-3"
    async with db.session_scope() as session:
        assert (await session.get(LogPatternBaseline, (vc, "esx-1", "hostd", MASK_VERSION))).started_at == baseline.started_at


async def test_log_pattern_backfill_watermarks_and_catchup(ledger_db, backfill_clock):
    vc = ledger_db
    assert await ingest(vc, log(0)) == 1
    await legacy(vc, 10, 30, 50)
    await legacy(vc, 20, version=2)
    await obsolete_pattern(vc)
    await backfill.log_pattern_backfill(Settings())
    first = await state()
    assert (first.pending_upper_id, first.upper_id, first.last_id, first.completed_at) == (50, None, 0, None)
    current, obsolete = await patterns()
    assert current.total_count == 1
    assert obsolete.pattern_version == 2

    async with db.session_scope() as session:
        await session.execute(delete(LogRecord).where(LogRecord.id.in_((30, 50))))
    await legacy(vc, 15, 60)
    backfill_clock(270)
    await backfill.log_pattern_backfill(Settings())
    complete = await state()
    assert (complete.upper_id, complete.last_id, complete.pending_upper_id) == (50, 50, 60)
    assert complete.completed_at is not None
    pattern, = await patterns()
    assert pattern.total_count == 4
    async with db.session_scope() as session:
        assert (await session.get(LogRecord, 60)).pattern_key is None
    await obsolete_pattern(vc)

    await legacy(vc, 55, 80)
    backfill_clock(270)
    await backfill.log_pattern_backfill(Settings())
    caught_up = await state()
    assert (caught_up.upper_id, caught_up.last_id, caught_up.pending_upper_id) == (50, 60, 80)
    assert caught_up.completed_at == complete.completed_at
    assert (await patterns())[0].total_count == 7
    await legacy(vc, 70)
    backfill_clock(270)
    await backfill.log_pattern_backfill(Settings())
    assert (await state()).last_id == 80
    assert (await patterns())[0].total_count == 8
    await backfill.log_pattern_backfill(Settings())
    pattern, = await patterns()
    assert pattern.total_count == 8
    async with db.session_scope() as session:
        rows = (await session.scalars(select(LogRecord))).all()
        assert all(row.pattern_key == pattern.pattern_key and row.pattern_version == MASK_VERSION for row in rows)
        assert await session.get(LogPatternBaseline, (vc, "legacy", "hostd", MASK_VERSION)) is not None


async def test_log_pattern_backfill_limits(ledger_db, monkeypatch, backfill_clock):
    monkeypatch.setattr(backfill, "CHUNK_SIZE", 2)
    monkeypatch.setattr(backfill, "MAX_ROWS_PER_RUN", 4)
    await legacy(ledger_db, 10, 20, 30, 40, 50)
    await backfill.log_pattern_backfill(Settings())
    backfill_clock(270)
    await backfill.log_pattern_backfill(Settings())
    progress = await state()
    assert (progress.last_id, progress.upper_id, progress.completed_at) == (40, 50, None)
    assert (await patterns())[0].total_count == 4
    await backfill.log_pattern_backfill(Settings())
    assert (await state()).completed_at is not None
    assert (await patterns())[0].total_count == 5


async def test_log_pattern_retention_and_cap(ledger_db):
    now = datetime.now(timezone.utc)
    for offset, name, age in [(0, "expired", 91), (1, "oldest", 20), (2, "older", 15), (3, "old", 10),
                              (4, "recent one", 2), (5, "recent two", 1)]:
        await ingest(ledger_db, log(offset, at=now - timedelta(days=age), message=name))
    await purge_retention(Settings(log_pattern_retention_days=0))
    assert len(await patterns()) == 6
    async with db.session_scope() as session:
        # 台帳の日時だけが期限を過ぎていても、ログが参照している型は残す。
        await session.execute(update(LogPattern).where(LogPattern.template == "recent two").values(
            last_seen_at=now - timedelta(days=95),
        ))
    await purge_retention(Settings(log_pattern_max_per_vcenter=4))
    assert {p.template for p in await patterns()} == {"old", "older", "recent one", "recent two"}
    await purge_retention(Settings(log_pattern_retention_days=0, log_pattern_max_per_vcenter=1))
    assert {p.template for p in await patterns()} == {"recent one", "recent two"}


def test_log_pattern_settings_and_warmup():
    with pytest.raises(ValidationError, match="LOG_PATTERN_RETENTION_DAYS"):
        Settings(log_retention_days=7, log_pattern_retention_days=6)
    assert Settings(log_pattern_retention_days=0).log_pattern_retention_days == 0
    assert not is_past_warmup(NOW, NOW - timedelta(days=4), None, 3)
    assert not is_past_warmup(NOW, None, NOW, 3)
    assert not is_past_warmup(NOW, NOW - timedelta(days=2), NOW, 3)
    assert not is_past_warmup(NOW - timedelta(days=5), NOW, NOW, 3)
    assert is_past_warmup(NOW, (NOW - timedelta(days=3)).replace(tzinfo=None), NOW, 3)


@pytest.mark.parametrize("ledger_db", ["postgres"], indirect=True)
async def test_log_pattern_parallel_updates_postgres(ledger_db, backfill_clock):
    vc = ledger_db
    await legacy(vc, 20)
    await backfill.log_pattern_backfill(Settings())
    backfill_clock(270)
    counts = await asyncio.wait_for(asyncio.gather(
        ingest(vc, log(1, severity="warning"), log(2, message="Another 1"), collector="test.first"),
        ingest(vc, log(1, message="Another 2"), log(2, severity="err"), collector="test.second"),
        backfill.log_pattern_backfill(Settings()),
    ), timeout=15)
    assert counts[:2] == [2, 2]
    by_template = {pattern.template: pattern for pattern in await patterns()}
    assert set(by_template) == {"Another <N>", "Path retried <N> times"}
    other = by_template["Another <N>"]
    retried = by_template["Path retried <N> times"]
    assert (other.total_count, retried.total_count, retried.max_severity_rank) == (2, 3, 3)


async def test_log_pattern_confirmation_waits_270_seconds(ledger_db, backfill_clock):
    settings = Settings()
    await legacy(ledger_db, 20)
    await backfill.log_pattern_backfill(settings)

    backfill_clock(269)
    await legacy(ledger_db, 10, 30)
    await backfill.log_pattern_backfill(settings)
    pending = await state()
    assert (pending.upper_id, pending.last_id, pending.pending_upper_id) == (None, 0, 20)
    assert as_utc(pending.pending_recorded_at) == NOW
    assert not await patterns()

    next_observation = backfill_clock(1)
    await backfill.log_pattern_backfill(settings)
    confirmed = await state()
    assert (confirmed.upper_id, confirmed.last_id, confirmed.pending_upper_id) == (20, 20, 30)
    assert as_utc(confirmed.pending_recorded_at) == next_observation
    assert (await patterns())[0].total_count == 2

    backfill_clock(269)
    await legacy(ledger_db, 40)
    await backfill.log_pattern_backfill(settings)
    pending = await state()
    assert (pending.last_id, pending.pending_upper_id) == (20, 30)
    assert as_utc(pending.pending_recorded_at) == next_observation
    assert (await patterns())[0].total_count == 4

    backfill_clock(1)
    await legacy(ledger_db, 25)
    await backfill.log_pattern_backfill(settings)
    confirmed = await state()
    assert (confirmed.last_id, confirmed.pending_upper_id) == (30, 40)
    assert (await patterns())[0].total_count == 5


async def test_log_pattern_ingestion_masks_before_transaction_and_warns(ledger_db, monkeypatch, caplog):
    actual_scope = runtime.session_scope
    actual_mask = runtime.mask_message
    in_transaction = False

    @asynccontextmanager
    async def track_scope(*args, **kwargs):
        nonlocal in_transaction
        async with actual_scope(*args, **kwargs) as session:
            in_transaction = True
            try:
                yield session
            finally:
                in_transaction = False

    def track_mask(message):
        assert not in_transaction
        return actual_mask(message)

    class UnreadableMessage(str):
        def find(self, *_args):
            raise ValueError("例外を起こすログ")

    monkeypatch.setattr(runtime, "session_scope", track_scope)
    monkeypatch.setattr(runtime, "mask_message", track_mask)
    caplog.set_level("WARNING", logger=runtime.__name__)
    row = log(0, message=UnreadableMessage("original log"))
    assert await ingest(ledger_db, row, row) == 1
    assert await ingest(ledger_db, row) == 0
    assert [p.template for p in await patterns()] == ["<UNPARSED>"]
    warnings = [record.getMessage() for record in caplog.records if record.name == runtime.__name__]
    assert len(warnings) == 1
    assert "log pattern masking failed count=1" in warnings[0]
    assert "original log" not in warnings[0]


@pytest.mark.parametrize("ledger_db", ["sqlite"], indirect=True)
async def test_log_pattern_backfill_skips_orphan_sqlite(ledger_db, backfill_clock):
    async with db.get_engine().connect() as conn:
        assert await conn.scalar(text("PRAGMA foreign_keys")) == 1
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            orphan_id = await conn.scalar(LogRecord.__table__.insert().values(
                vcenter_id=uuid4(), collector_id="old.logs", source_id="orphan", host="esx",
                log_kind="hostd", file_generation="old", byte_offset=0,
                effective_at=NOW, collected_at=NOW, message="Orphan 12",
            ).returning(LogRecord.id))
            await conn.commit()
        finally:
            await conn.rollback()
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        assert await conn.scalar(text("PRAGMA foreign_keys")) == 1

    settings = Settings()
    await backfill.log_pattern_backfill(settings)
    backfill_clock(270)
    await backfill.log_pattern_backfill(settings)
    progress = await state()
    assert progress.last_id == progress.upper_id == orphan_id
    assert progress.completed_at is not None
    async with db.session_scope() as session:
        orphan = await session.get(LogRecord, orphan_id)
        assert orphan.pattern_key is None
    assert not await patterns()
