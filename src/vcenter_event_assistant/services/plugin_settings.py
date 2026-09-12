"""Operator-managed collector plugin settings stored in the database.

``build_collector_registry`` は I/O を行わない純関数に保ちたいため、DB からの読み出しは
ここに集約し、辞書として registry ビルダへ渡す。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import CollectorPluginSetting
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.settings import Settings

_MIN_INTERVAL_SECONDS = 10


async def load_collector_db_overrides(
    session: AsyncSession,
) -> dict[str, dict[str, Any]]:
    """plugin_id → 設定辞書。``None`` の列は下位ソースへ委譲するため含めない。"""
    result = await session.execute(select(CollectorPluginSetting))
    overrides: dict[str, dict[str, Any]] = {}
    for row in result.scalars().all():
        values: dict[str, Any] = {}
        if row.enabled is not None:
            values["enabled"] = row.enabled
        if row.interval_seconds is not None:
            values["interval_seconds"] = row.interval_seconds
        if row.timeout_seconds is not None:
            values["timeout_seconds"] = row.timeout_seconds
        if row.config_values:
            values["config_values"] = dict(row.config_values)
        if values:
            overrides[row.plugin_id] = values
    return overrides


async def load_collector_db_overrides_with_settings(
    settings: Settings,
) -> dict[str, dict[str, Any]]:
    """リクエストスコープ外（lifespan など）から使う ``session_scope`` 版。"""
    async with session_scope(settings=settings) as session:
        return await load_collector_db_overrides(session)


async def update_collector_setting(
    session: AsyncSession,
    plugin_id: str,
    *,
    enabled: bool | None = None,
    interval_seconds: int | None = None,
    timeout_seconds: float | None = None,
) -> CollectorPluginSetting:
    """PATCH 由来の部分更新を保存する。``None`` の引数は変更しない。

    「未設定へ戻す」操作は本フェーズの API では扱わないため、``None`` は一貫して
    「この呼び出しでは触れない」を意味する。
    """
    if interval_seconds is not None and interval_seconds < _MIN_INTERVAL_SECONDS:
        raise ValueError(
            f"interval_seconds must be at least {_MIN_INTERVAL_SECONDS} seconds"
        )
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    row = await session.get(CollectorPluginSetting, plugin_id)
    if row is None:
        row = CollectorPluginSetting(plugin_id=plugin_id)
        session.add(row)
    if enabled is not None:
        row.enabled = enabled
    if interval_seconds is not None:
        row.interval_seconds = interval_seconds
    if timeout_seconds is not None:
        row.timeout_seconds = timeout_seconds
    await session.flush()
    return row
