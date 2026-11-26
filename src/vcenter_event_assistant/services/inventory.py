"""インベントリの観測を保存し、有効な vCenter を順に収集する。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timedelta
from threading import Thread
from time import monotonic
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
from vcenter_event_assistant.collectors.inventory_config import (
    ConfigBaseline,
    ConfigObservation,
    ConfigReadTimeout,
    read_inventory_config,
)
from vcenter_event_assistant.db.models import (
    InventoryConfigDiff,
    InventoryObject,
    InventoryRelation,
    InventorySyncRun,
    InventorySyncState,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.mocks.mock_inventory import (
    mock_inventory,
    mock_inventory_config,
)
from vcenter_event_assistant.plugins.runtime import _safe_error
from vcenter_event_assistant.services.inventory_config import (
    config_baselines,
    persist_inventory_config,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

_locks: WeakValueDictionary[UUID, asyncio.Lock] = WeakValueDictionary()
_WORKER_COUNT = 2
_reads_closed = False
_CONFIG_DEADLINE_FRACTION = 0.8


class _ConfigFuture(Future[ConfigObservation | None]):
    # 構成の結果を受け取った後も、切断中はスレッド枠を空けない。
    thread: Thread


_reads: dict[UUID, _ConfigFuture] = {}


class InventoryReadTimeout(TimeoutError):
    """観測の読み取りがタイムアウトした。"""


class InventoryReadStillRunning(Exception):
    """同じ vCenter の前回の読み取りが残っている。"""


class InventoryWorkerUnavailable(Exception):
    """収集用の専用スレッドに空きがない。"""


class InventoryReadsClosed(Exception):
    """アプリの終了中で新しい読み取りを開始できない。"""


class ConfigReadMissing(Exception):
    """有効な構成読み取りから結果が返らなかった。"""


_READ_ERRORS = {
    InventoryReadTimeout: "読み取りがタイムアウトしました。",
    ConfigReadTimeout: "構成の読み取りがタイムアウトしました。",
    InventoryReadStillRunning: "前回の読み取りがまだ実行中です。",
    InventoryWorkerUnavailable: "専用スレッドに空きがありません。",
    InventoryReadsClosed: "インベントリの読み取り受付は終了しました。",
    ConfigReadMissing: "構成の読み取り結果を受け取れませんでした。",
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
    vcenter: VCenter,
    settings: Settings,
    *,
    after_relations: Callable[[InventoryObservation, datetime, object], None]
    | None = None,
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
        content = si.RetrieveContent()
        observation = read_inventory(content)
        observed_at = utcnow()
        if after_relations is not None:
            after_relations(observation, observed_at, content)
        return observation
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
    settings: Settings,
    vcenter_id: UUID,
    started_at: datetime,
    exc: Exception,
    *,
    relations: bool = True,
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
            failed_at = utcnow()
            if relations:
                state.last_started_at = started_at
                state.last_failure_at = failed_at
                state.last_error = error
            if settings.inventory_config_enabled:
                state.config_last_failure_at = failed_at
                state.config_last_error = error
    except Exception as record_error:
        # 削除が失敗記録と重なった場合も外部キーが状態の再作成を防ぐ。
        logger.warning(
            "inventory failure record failed vcenter_id=%s: %s (sync failure: %s)",
            vcenter_id,
            _safe_error(record_error),
            error,
        )
        return
    logger.warning(
        "%s vcenter_id=%s: %s",
        "inventory sync failed" if relations else "inventory config sync failed",
        vcenter_id,
        error,
    )


async def _read_with_timeout(
    vcenter: VCenter,
    settings: Settings,
    baseline_uuid: str | None = None,
    baselines: dict[str, ConfigBaseline] | None = None,
) -> tuple[InventoryObservation, datetime, _ConfigFuture, float]:
    if _reads_closed:
        raise InventoryReadsClosed
    for vcenter_id, pending in tuple(_reads.items()):
        if not pending.thread.is_alive():
            _reads.pop(vcenter_id, None)
    if vcenter.id in _reads:
        raise InventoryReadStillRunning
    if len(_reads) >= _WORKER_COUNT:
        raise InventoryWorkerUnavailable

    relation_future: Future[tuple[InventoryObservation, datetime]] = Future()
    config_future = _ConfigFuture()
    # 非同期側のタイムアウトで、実行中の読み取り結果は取り消さない。
    relation_future.set_running_or_notify_cancel()
    config_future.set_running_or_notify_cancel()
    started = monotonic()
    expires = started + settings.inventory_sync_timeout_seconds

    def read() -> None:
        deadline = (
            monotonic()
            + settings.inventory_sync_timeout_seconds * _CONFIG_DEADLINE_FRACTION
        )

        def publish(
            observation: InventoryObservation, observed_at: datetime, content: object
        ) -> None:
            relation_future.set_result((observation, observed_at))
            if not settings.inventory_config_enabled:
                return
            try:
                config = read_inventory_config(
                    content,
                    vcenter.id,
                    (baselines or {})
                    if baseline_uuid == observation.instance_uuid
                    else {},
                    deadline=deadline,
                )
                if monotonic() >= expires:
                    raise ConfigReadTimeout
            except BaseException as exc:
                config_future.set_exception(exc)
            else:
                config_future.set_result(config)

        try:
            observation = read_vcenter_inventory(
                vcenter, settings, after_relations=publish
            )
            if not relation_future.done():
                relation_future.set_result((observation, utcnow()))
        except BaseException as exc:
            if not relation_future.done():
                relation_future.set_exception(exc)
        finally:
            if not config_future.done():
                config_future.set_result(None)

    config_future.thread = Thread(
        target=read, name=f"inventory-{vcenter.id}", daemon=True
    )
    config_future.thread.start()
    _reads[vcenter.id] = config_future
    try:
        async with asyncio.timeout(max(0, expires - monotonic())):
            observation, observed_at = await asyncio.wrap_future(relation_future)
        return observation, observed_at, config_future, expires
    except TimeoutError as exc:
        raise InventoryReadTimeout from exc
    except vim.fault.HostConnectFault as exc:
        # pyVmomi は最初の RetrieveContent のソケット例外を接続障害で包む。
        if isinstance(exc.__context__, TimeoutError):
            raise InventoryReadTimeout from exc
        raise


async def _wait_for_config(
    future: Future[ConfigObservation | None],
    expires: float,
) -> ConfigObservation | None:
    if future.done():
        return future.result()
    timeout = asyncio.timeout(max(0, expires - monotonic()))
    try:
        async with timeout:
            return await asyncio.wrap_future(future)
    except TimeoutError as exc:
        if timeout.expired():
            raise ConfigReadTimeout from exc
        raise


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
                baseline_uuid = None
                baselines: dict[str, ConfigBaseline] = {}
                if settings.inventory_config_enabled:
                    async with session_scope(settings=settings) as session:
                        baseline_uuid, baselines = await config_baselines(
                            session, vcenter.id
                        )
            except Exception as exc:
                # 構成の準備だけが失敗しても、関係の読み取りと保存は続ける。
                config_setup_error = exc
                read_settings = settings.model_copy(
                    update={"inventory_config_enabled": False}
                )
            else:
                config_setup_error = None
                read_settings = settings

            future = None
            try:
                if settings.mock_mode:
                    observation = mock_inventory(started_at, vcenter_name=vcenter.name)
                    observed_at = utcnow()
                else:
                    (
                        observation,
                        observed_at,
                        future,
                        expires,
                    ) = await _read_with_timeout(
                        vcenter, read_settings, baseline_uuid, baselines
                    )
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
                continue

            if not settings.inventory_config_enabled:
                continue
            try:
                if config_setup_error is not None:
                    raise config_setup_error
                if settings.mock_mode:
                    config = mock_inventory_config(
                        started_at,
                        observation=observation,
                        vcenter_name=vcenter.name,
                        baselines=baselines
                        if baseline_uuid == observation.instance_uuid
                        else {},
                    )
                else:
                    assert future is not None
                    config = await _wait_for_config(future, expires)
                if config is None:
                    raise ConfigReadMissing
                async with session_scope(settings=settings) as session:
                    await persist_inventory_config(session, vcenter.id, config)
            except Exception as exc:
                await _record_failure(
                    settings, vcenter.id, started_at, exc, relations=False
                )
            finally:
                if future is not None and not future.thread.is_alive():
                    _reads.pop(vcenter.id, None)


async def purge_old_inventory(session: AsyncSession, *, settings: Settings) -> None:
    """保持期間を過ぎた関係、管理対象、観測時刻、構成の差分を削除する。"""
    now = utcnow()
    cutoff = now - timedelta(days=settings.event_retention_days)
    await session.execute(
        delete(InventoryRelation).where(InventoryRelation.valid_to < cutoff)
    )
    await session.execute(
        delete(InventoryObject).where(InventoryObject.removed_at < cutoff)
    )
    await session.execute(
        delete(InventorySyncRun).where(InventorySyncRun.observed_at < cutoff)
    )
    config_cutoff = now - timedelta(days=settings.inventory_config_retention_days)
    await session.execute(
        delete(InventoryConfigDiff).where(
            InventoryConfigDiff.observed_at < config_cutoff
        )
    )
