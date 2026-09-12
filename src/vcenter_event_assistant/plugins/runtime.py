"""Execution and persistence boundary for collector plugins."""

from __future__ import annotations

import asyncio
import logging
import math
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectionContext,
    VCenterTarget,
)

from vcenter_event_assistant.collectors.connection import connect_vcenter, disconnect
from vcenter_event_assistant.db.models import (
    CollectorRunState,
    EventRecord,
    IngestionState,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins.registry import CollectorRegistration
from vcenter_event_assistant.plugins.remote import RemoteCollectorPlugin
from vcenter_event_assistant.plugins.wire import ConnectionParams
from vcenter_event_assistant.rules.notable import clamp_notable_total, score_event
from vcenter_event_assistant.services.event_scores import load_event_score_delta_map
from vcenter_event_assistant.services.ingestion import _insert_on_conflict_do_nothing
from vcenter_event_assistant.settings import Settings

_locks: dict[tuple[str, str], asyncio.Lock] = {}
_limiter: asyncio.Semaphore | None = None
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CollectorRunResult:
    plugin_id: str
    status: str
    events_inserted: int = 0
    metrics_inserted: int = 0
    error: str | None = None


async def drain_collector_runs(plugin_ids: set[str]) -> None:
    """Wait until currently running calls for a registry generation release their locks."""
    active = [
        lock
        for (plugin_id, _), lock in tuple(_locks.items())
        if plugin_id in plugin_ids and lock.locked()
    ]
    for lock in active:
        await lock.acquire()
        lock.release()


def _safe_error(exc: BaseException) -> str:
    # Detailed plugin exceptions can contain credentials or response bodies.
    return f"{type(exc).__name__}: collector execution failed"


def _connection_params(vcenter: VCenter, settings: Settings) -> ConnectionParams:
    """インプロセス実行とワーカーへの転送で共有する接続パラメータ。"""
    return ConnectionParams(
        host=vcenter.host,
        protocol=vcenter.protocol,
        port=vcenter.port,
        username=vcenter.username,
        password=vcenter.password,
        verify_ssl=vcenter.verify_ssl,
        proxy_url=settings.vcenter_http_proxy,
        ca_bundle_path=settings.vcenter_ca_bundle,
    )


@asynccontextmanager
async def _open_connection(params: ConnectionParams):
    si = await asyncio.to_thread(
        connect_vcenter,
        host=params.host,
        protocol=params.protocol,
        port=params.port,
        username=params.username,
        password=params.password,
        proxy_url=params.proxy_url,
        verify_ssl=params.verify_ssl,
        ca_bundle_path=params.ca_bundle_path,
    )
    try:
        yield si
    finally:
        await asyncio.to_thread(disconnect, si)


async def _state_row(
    session, vcenter_id, registration: CollectorRegistration
) -> CollectorRunState:
    result = await session.execute(
        select(CollectorRunState).where(
            CollectorRunState.vcenter_id == vcenter_id,
            CollectorRunState.collector_id == registration.plugin_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = CollectorRunState(
            vcenter_id=vcenter_id, collector_id=registration.plugin_id, status="idle"
        )
        session.add(row)
        await session.flush()
    if registration.plugin is not None:
        row.collector_version = registration.plugin.manifest.version
    return row


async def _mark_started(
    settings: Settings, vcenter_id, registration: CollectorRegistration
) -> None:
    async with session_scope(settings=settings) as session:
        row = await _state_row(session, vcenter_id, registration)
        row.status = "running"
        row.last_started_at = datetime.now(timezone.utc)
        row.error_message = None


async def _mark_failed(
    settings: Settings, vcenter_id, registration: CollectorRegistration, error: str
) -> None:
    async with session_scope(settings=settings) as session:
        row = await _state_row(session, vcenter_id, registration)
        row.status = "failed"
        row.last_failure_at = datetime.now(timezone.utc)
        row.error_message = error


def _validate_batch(
    registration: CollectorRegistration, batch: CollectionBatch
) -> None:
    assert registration.plugin is not None
    manifest = registration.plugin.manifest
    if batch.events and "event" not in manifest.data_kinds:
        raise ValueError("collector emitted undeclared event data")
    if batch.metrics and "metric" not in manifest.data_kinds:
        raise ValueError("collector emitted undeclared metric data")
    declared = {definition.key for definition in manifest.metric_definitions}
    for sample in batch.metrics:
        if sample.metric_key not in declared:
            raise ValueError(f"undeclared metric key: {sample.metric_key}")
        if not math.isfinite(sample.value):
            raise ValueError(f"non-finite metric value: {sample.metric_key}")
        if sample.sampled_at.tzinfo is None:
            raise ValueError("metric sampled_at must be timezone-aware")
    for event in batch.events:
        if event.occurred_at.tzinfo is None:
            raise ValueError("event occurred_at must be timezone-aware")


async def _persist_batch(
    settings: Settings,
    vcenter_id,
    registration: CollectorRegistration,
    batch: CollectionBatch,
) -> tuple[int, int]:
    assert registration.plugin is not None
    async with session_scope(settings=settings) as session:
        deltas = await load_event_score_delta_map(session) if batch.events else {}
        events_inserted = 0
        for event in batch.events:
            notable = score_event(
                event_type=event.event_type,
                severity=event.severity,
                message=event.message,
            )
            result = await _insert_on_conflict_do_nothing(
                session,
                EventRecord,
                {
                    "collector_id": registration.plugin_id,
                    "vcenter_id": vcenter_id,
                    "occurred_at": event.occurred_at,
                    "event_type": event.event_type,
                    "message": event.message,
                    "severity": event.severity,
                    "user_name": event.user_name,
                    "entity_name": event.entity_name,
                    "entity_type": event.entity_type,
                    "vmware_key": event.vmware_key,
                    "chain_id": event.chain_id,
                    "notable_score": clamp_notable_total(
                        notable.score, deltas.get(event.event_type, 0)
                    ),
                    "notable_tags": notable.tags,
                },
                index_elements=["vcenter_id", "collector_id", "vmware_key"],
            )
            events_inserted += result.rowcount or 0
        metrics_inserted = 0
        for sample in batch.metrics:
            result = await _insert_on_conflict_do_nothing(
                session,
                MetricSample,
                {
                    "collector_id": registration.plugin_id,
                    "vcenter_id": vcenter_id,
                    "sampled_at": sample.sampled_at,
                    "entity_type": sample.entity_type,
                    "entity_moid": sample.entity_moid,
                    "entity_name": sample.entity_name,
                    "metric_key": sample.metric_key,
                    "value": sample.value,
                },
                index_elements=[
                    "vcenter_id",
                    "sampled_at",
                    "entity_moid",
                    "metric_key",
                ],
            )
            metrics_inserted += result.rowcount or 0
        if batch.next_cursor is not None:
            state_result = await session.execute(
                select(IngestionState).where(
                    IngestionState.vcenter_id == vcenter_id,
                    IngestionState.kind == registration.plugin_id,
                )
            )
            state = state_result.scalar_one_or_none()
            if state is None:
                state = IngestionState(
                    vcenter_id=vcenter_id, kind=registration.plugin_id
                )
                session.add(state)
            state.cursor_value = batch.next_cursor
        run_state = await _state_row(session, vcenter_id, registration)
        run_state.status = "ok"
        run_state.last_success_at = datetime.now(timezone.utc)
        run_state.events_inserted = events_inserted
        run_state.metrics_inserted = metrics_inserted
        run_state.error_message = None
        return events_inserted, metrics_inserted


async def run_collector_for_vcenter(
    settings: Settings, registration: CollectorRegistration, vcenter_id
) -> CollectorRunResult:
    global _limiter
    if (
        registration.plugin is None
        or registration.config is None
        or registration.status != "enabled"
    ):
        return CollectorRunResult(
            registration.plugin_id, "failed", error=registration.error
        )
    key = (registration.plugin_id, str(vcenter_id))
    lock = _locks.setdefault(key, asyncio.Lock())
    if lock.locked():
        return CollectorRunResult(
            registration.plugin_id, "skipped", error="already running"
        )
    if _limiter is None:
        _limiter = asyncio.Semaphore(settings.ingestion_concurrency)
    async with lock, _limiter:
        await _mark_started(settings, vcenter_id, registration)
        try:
            async with session_scope(settings=settings) as session:
                vc = (
                    await session.execute(
                        select(VCenter).where(VCenter.id == vcenter_id)
                    )
                ).scalar_one()
                state = (
                    await session.execute(
                        select(IngestionState).where(
                            IngestionState.vcenter_id == vcenter_id,
                            IngestionState.kind == registration.plugin_id,
                        )
                    )
                ).scalar_one_or_none()
                params = _connection_params(vc, settings)
                context = CollectionContext(
                    target=VCenterTarget(
                        vc.id,
                        vc.name,
                        vc.host,
                        vc.protocol,
                        vc.port,
                        vc.username,
                        vc.verify_ssl,
                    ),
                    config=registration.config.values,
                    previous_cursor=state.cursor_value if state else None,
                    open_vcenter_connection=lambda: _open_connection(params),
                    mock_mode=settings.mock_mode,
                )
            # 収集は DB セッションの外で行う。外部プラグインは timeout まで走りうるため、
            # その間 DB 接続を占有させない。
            timeout_seconds = registration.config.timeout_seconds
            if isinstance(registration.plugin, RemoteCollectorPlugin):
                # ワーカーが自前でタイムアウトを監視し、超過時はプロセスごと kill する。
                batch = await registration.plugin.collect_with_connection(
                    context, params, timeout=timeout_seconds
                )
            else:
                async with asyncio.timeout(timeout_seconds):
                    batch = await registration.plugin.collect(context)
            _validate_batch(registration, batch)
            events, metrics = await _persist_batch(
                settings, vcenter_id, registration, batch
            )
            return CollectorRunResult(registration.plugin_id, "ok", events, metrics)
        except Exception as exc:
            logger.exception(
                "collector execution failed plugin_id=%s vcenter_id=%s",
                registration.plugin_id,
                vcenter_id,
            )
            error = _safe_error(exc)
            await _mark_failed(settings, vcenter_id, registration, error)
            return CollectorRunResult(registration.plugin_id, "failed", error=error)
