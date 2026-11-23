"""インベントリの観測を保存し、有効な vCenter を順に収集する。"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Future
from datetime import datetime, timedelta
from threading import Thread
from uuid import UUID
from weakref import WeakValueDictionary

from pyVmomi import vim
from sqlalchemy import bindparam, delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.collectors.connection import connect_vcenter, disconnect
from vcenter_event_assistant.collectors.inventory import (
    InventoryObservation,
    read_inventory,
)
from vcenter_event_assistant.db.models import (
    InventoryObject,
    InventoryRelation,
    InventorySyncRun,
    InventorySyncState,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.mocks.mock_inventory import mock_inventory
from vcenter_event_assistant.plugins.runtime import _safe_error
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

_locks: WeakValueDictionary[UUID, asyncio.Lock] = WeakValueDictionary()
_WORKER_COUNT = 2
_reads_closed = False
_reads: dict[UUID, Future[InventoryObservation]] = {}


class InventoryReadTimeout(TimeoutError):
    """観測の読み取りがタイムアウトした。"""


class InventoryReadStillRunning(Exception):
    """同じ vCenter の前回の読み取りが残っている。"""


class InventoryWorkerUnavailable(Exception):
    """収集用の専用スレッドに空きがない。"""


class InventoryReadsClosed(Exception):
    """アプリの終了中で新しい読み取りを開始できない。"""


_READ_ERRORS = {
    InventoryReadTimeout: "読み取りがタイムアウトしました。",
    InventoryReadStillRunning: "前回の読み取りがまだ実行中です。",
    InventoryWorkerUnavailable: "専用スレッドに空きがありません。",
    InventoryReadsClosed: "インベントリの読み取り受付は終了しました。",
}


def start_inventory_reads() -> None:
    """アプリの起動時にインベントリの読み取りを受け付ける。"""
    global _reads_closed
    _reads_closed = False


def shutdown_inventory_reads() -> None:
    """新しい読み取りの受付を閉じる。実行中のデーモンスレッドは終了を待たない。

    再起動後も読み取りスレッドの総数を抑えるため、止まった読み取りの
    数えに使う ``_reads`` は意図して残す。
    """
    global _reads_closed
    _reads_closed = True


def read_vcenter_inventory(
    vcenter: VCenter, settings: Settings
) -> InventoryObservation:
    """接続から切断までを専用スレッドで実行する。"""
    si = connect_vcenter(
        host=vcenter.host,
        protocol=vcenter.protocol,
        port=vcenter.port,
        username=vcenter.username,
        password=vcenter.password,
        verify_ssl=vcenter.verify_ssl,
        proxy_url=settings.vcenter_http_proxy,
        ca_bundle_path=settings.vcenter_ca_bundle,
        http_connection_timeout=settings.inventory_sync_timeout_seconds,
    )
    try:
        return read_inventory(si.RetrieveContent())
    finally:
        try:
            disconnect(si)
        except Exception as exc:
            logger.warning(
                "inventory disconnect failed vcenter_id=%s: %s",
                vcenter.id,
                _safe_error(exc),
            )


async def persist_inventory(
    session: AsyncSession,
    vcenter_id: UUID,
    observation: InventoryObservation,
    *,
    observed_at: datetime,
    started_at: datetime,
) -> None:
    """管理対象・関係・観測時刻・収集状態を呼び出し元のトランザクションで更新する。"""
    state = await session.get(InventorySyncState, vcenter_id)
    if state is None:
        state = InventorySyncState(vcenter_id=vcenter_id)
        session.add(state)
    t = as_utc(observed_at)
    if state.last_success_at is not None:
        t = max(t, as_utc(state.last_success_at))
    reset = (
        state.instance_uuid is not None
        and state.instance_uuid != observation.instance_uuid
    )
    objects = observation.objects
    relations = InventoryRelation.__table__
    open_filter = (relations.c.vcenter_id == vcenter_id, relations.c.valid_to.is_(None))
    if reset:
        logger.warning(
            "inventory instance changed vcenter_id=%s old_instance_uuid=%s new_instance_uuid=%s",
            vcenter_id,
            state.instance_uuid,
            observation.instance_uuid,
        )
        await session.execute(update(relations).where(*open_filter).values(valid_to=t))
        await session.execute(
            update(InventoryObject)
            .where(
                InventoryObject.vcenter_id == vcenter_id,
                InventoryObject.removed_at.is_(None),
            )
            .values(removed_at=t)
        )
        existing = {}
    else:
        rows = await session.execute(
            select(
                relations.c.id,
                relations.c.kind,
                relations.c.child_moid,
                relations.c.parent_moid,
            ).where(*open_filter)
        )
        existing = {
            (kind, child, parent): row_id for row_id, kind, child, parent in rows
        }

    current = observation.relations | {
        (kind, child, parent)
        for kind, child, parent in existing
        if (kind, child) in observation.carry_over
        and child in objects
        and parent in objects
    }
    if closed := existing.keys() - current:
        await session.execute(
            update(relations)
            .where(
                relations.c.id == bindparam("relation_id"),
                relations.c.valid_to.is_(None),
            )
            .values(valid_to=t),
            [{"relation_id": existing[edge]} for edge in closed],
        )
    if opened := current - existing.keys():
        await session.execute(
            insert(relations),
            [
                dict(
                    vcenter_id=vcenter_id,
                    kind=kind,
                    child_moid=child,
                    parent_moid=parent,
                    valid_from=t,
                )
                for kind, child, parent in opened
            ],
        )

    stored = {
        obj.moid: obj
        for obj in await session.scalars(
            select(InventoryObject).where(InventoryObject.vcenter_id == vcenter_id)
        )
    }
    for moid, data in objects.items():
        obj = stored.pop(moid, None)
        if obj is None:
            session.add(
                InventoryObject(
                    vcenter_id=vcenter_id,
                    moid=moid,
                    name=data.name if data.name is not None else moid,
                    entity_type=data.entity_type,
                    first_seen_at=t,
                )
            )
        else:
            if data.name is not None:
                obj.name = data.name
            obj.entity_type = data.entity_type
            # 前の vCenter でしか見えていなかった対象が、後の観測で戻ることもある。
            if reset or (
                obj.removed_at is not None
                and state.first_success_at is not None
                and as_utc(obj.first_seen_at) < as_utc(state.first_success_at)
            ):
                obj.first_seen_at = t
            obj.removed_at = None
    for obj in stored.values():
        if obj.removed_at is None:
            obj.removed_at = t

    if state.object_count and len(objects) * 2 <= state.object_count:
        state.last_warning = f"管理対象が前回の {state.object_count} 件から {len(objects)} 件に減りました。"
        state.last_warning_at = t
    if reset or state.first_success_at is None:
        state.first_success_at = t
    state.instance_uuid = observation.instance_uuid
    state.last_started_at = as_utc(started_at)
    state.last_success_at = t
    state.object_count = len(objects)
    state.relation_count = len(current)
    session.add(InventorySyncRun(vcenter_id=vcenter_id, observed_at=t))


async def _record_failure(
    settings: Settings, vcenter_id: UUID, started_at: datetime, exc: Exception
) -> None:
    detail = _READ_ERRORS.get(type(exc))
    error = f"{type(exc).__name__}: {detail}" if detail else _safe_error(exc)
    try:
        async with session_scope(settings=settings) as session:
            if await session.get(VCenter, vcenter_id) is None:
                logger.warning(
                    "inventory sync target deleted vcenter_id=%s: %s", vcenter_id, error
                )
                return
            state = await session.get(InventorySyncState, vcenter_id)
            if state is None:
                state = InventorySyncState(vcenter_id=vcenter_id)
                session.add(state)
            state.last_started_at = started_at
            state.last_failure_at = utcnow()
            state.last_error = error
    except Exception as record_error:
        # 削除が失敗記録と重なった場合も外部キーが状態の再作成を防ぐ。
        logger.warning(
            "inventory failure record failed vcenter_id=%s: %s (sync failure: %s)",
            vcenter_id,
            _safe_error(record_error),
            error,
        )
        return
    logger.warning("inventory sync failed vcenter_id=%s: %s", vcenter_id, error)


async def _read_with_timeout(
    vcenter: VCenter, settings: Settings
) -> InventoryObservation:
    if _reads_closed:
        raise InventoryReadsClosed
    for vcenter_id, pending in tuple(_reads.items()):
        if pending.done():
            _reads.pop(vcenter_id, None)
    if vcenter.id in _reads:
        raise InventoryReadStillRunning
    if len(_reads) >= _WORKER_COUNT:
        raise InventoryWorkerUnavailable

    future: Future[InventoryObservation] = Future()
    # 非同期側のタイムアウトでも実行中の読み取りは追跡し続ける。
    future.set_running_or_notify_cancel()

    def read() -> None:
        try:
            result = read_vcenter_inventory(vcenter, settings)
        except BaseException as exc:
            future.set_exception(exc)
        else:
            future.set_result(result)

    Thread(target=read, name=f"inventory-{vcenter.id}", daemon=True).start()
    _reads[vcenter.id] = future
    try:
        async with asyncio.timeout(settings.inventory_sync_timeout_seconds):
            return await asyncio.wrap_future(future)
    except TimeoutError as exc:
        raise InventoryReadTimeout from exc
    except vim.fault.HostConnectFault as exc:
        # pyVmomi は最初の RetrieveContent のソケット例外を接続障害で包む。
        if isinstance(exc.__context__, TimeoutError):
            raise InventoryReadTimeout from exc
        raise
    finally:
        if future.done():
            _reads.pop(vcenter.id, None)


async def sync_inventory(settings: Settings) -> None:
    """有効な vCenter を順に観測し、失敗したときも次の vCenter へ進む。"""
    if not settings.inventory_sync_enabled:
        return

    try:
        await _sync_enabled_vcenters(settings)
    except Exception:
        logger.exception("inventory sync job failed")


async def _sync_enabled_vcenters(settings: Settings) -> None:
    async with session_scope(settings=settings) as session:
        targets = (
            await session.scalars(
                select(VCenter)
                .where(VCenter.is_enabled.is_(True))
                .order_by(VCenter.name)
            )
        ).all()

    for vcenter in targets:
        lock = _locks.setdefault(vcenter.id, asyncio.Lock())
        async with lock:
            started_at = utcnow()
            try:
                observation = (
                    mock_inventory(started_at, vcenter_name=vcenter.name)
                    if settings.mock_mode
                    else await _read_with_timeout(vcenter, settings)
                )
                observed_at = utcnow()
                async with session_scope(settings=settings) as session:
                    await persist_inventory(
                        session,
                        vcenter.id,
                        observation,
                        observed_at=observed_at,
                        started_at=started_at,
                    )
            except Exception as exc:
                await _record_failure(settings, vcenter.id, started_at, exc)


async def purge_old_inventory(session: AsyncSession, *, settings: Settings) -> None:
    """保持期間を過ぎた閉じた関係、見えなくなった対象、観測時刻を削除する。"""
    cutoff = utcnow() - timedelta(days=settings.event_retention_days)
    await session.execute(
        delete(InventoryRelation).where(InventoryRelation.valid_to < cutoff)
    )
    await session.execute(
        delete(InventoryObject).where(InventoryObject.removed_at < cutoff)
    )
    await session.execute(
        delete(InventorySyncRun).where(InventorySyncRun.observed_at < cutoff)
    )
