"""インベントリの影響範囲・構成の差分・収集状態を返す。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.auth_deps import RequireViewer
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.schemas.base import UtcDateTime
from vcenter_event_assistant.api.schemas.inventory import (
    InventoryConfigDiffResponse,
    InventoryImpactResponse,
    InventoryStatusResponse,
    InventoryVCenterStatus,
)
from vcenter_event_assistant.db.models import InventorySyncState, VCenter
from vcenter_event_assistant.services.inventory_config_diffs import (
    get_inventory_config_diffs,
    inventory_config_enabled,
)
from vcenter_event_assistant.services.inventory_impact import get_inventory_impact
from vcenter_event_assistant.settings import Settings

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get(
    "/impact",
    dependencies=[RequireViewer],
    response_model=InventoryImpactResponse,
    response_model_exclude_unset=True,
)
async def inventory_impact(
    vcenter_id: UUID,
    entity_moid: Annotated[str, Query(min_length=1, max_length=256)],
    at: Annotated[UtcDateTime | None, Query()] = None,
    from_time: Annotated[UtcDateTime | None, Query(alias="from")] = None,
    to_time: Annotated[UtcDateTime | None, Query(alias="to")] = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> InventoryImpactResponse:
    if (from_time is None) != (to_time is None):
        raise HTTPException(
            status_code=422, detail="from and to must be provided together"
        )
    if from_time is not None and to_time is not None and from_time > to_time:
        raise HTTPException(status_code=422, detail="from must not be after to")
    result = await get_inventory_impact(
        session,
        settings,
        vcenter_id=vcenter_id,
        moid=entity_moid,
        at=at,
        from_time=from_time,
        to_time=to_time,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="vCenter not found")
    return result


@router.get(
    "/config-diffs",
    dependencies=[RequireViewer],
    response_model=InventoryConfigDiffResponse,
    description="指定期間に重なる、観測した構成項目の違いを返す。装置の交換は観測した値から見分けられない場合がある。",
)
async def inventory_config_diffs(
    vcenter_id: UUID,
    entity_moid: Annotated[str, Query(min_length=1, max_length=256)],
    from_time: Annotated[UtcDateTime | None, Query(alias="from")] = None,
    to_time: Annotated[UtcDateTime | None, Query(alias="to")] = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> InventoryConfigDiffResponse:
    if (from_time is None) != (to_time is None):
        raise HTTPException(
            status_code=422, detail="from and to must be provided together"
        )
    if from_time is not None and to_time is not None and from_time > to_time:
        raise HTTPException(status_code=422, detail="from must not be after to")
    result = await get_inventory_config_diffs(
        session,
        settings,
        vcenter_id=vcenter_id,
        moid=entity_moid,
        from_time=from_time,
        to_time=to_time,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="vCenter not found")
    return result


@router.get(
    "/status", dependencies=[RequireViewer], response_model=InventoryStatusResponse
)
async def inventory_status(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> InventoryStatusResponse:
    rows = await session.execute(
        select(
            VCenter.id.label("vcenter_id"),
            VCenter.name.label("vcenter_name"),
            VCenter.is_enabled,
            InventorySyncState.first_success_at,
            InventorySyncState.last_started_at,
            InventorySyncState.last_success_at,
            InventorySyncState.last_failure_at,
            InventorySyncState.last_error,
            InventorySyncState.last_warning,
            InventorySyncState.last_warning_at,
            InventorySyncState.object_count,
            InventorySyncState.relation_count,
            InventorySyncState.config_first_success_at,
            InventorySyncState.config_last_started_at,
            InventorySyncState.config_last_success_at,
            InventorySyncState.config_last_failure_at,
            InventorySyncState.config_last_error,
            InventorySyncState.config_last_warning,
            InventorySyncState.config_last_warning_at,
            InventorySyncState.config_object_count,
            InventorySyncState.config_deferred_count,
        )
        .outerjoin(InventorySyncState, InventorySyncState.vcenter_id == VCenter.id)
        .order_by(VCenter.name, VCenter.id)
    )
    return InventoryStatusResponse(
        enabled=settings.scheduler_enabled and settings.inventory_sync_enabled,
        config_enabled=inventory_config_enabled(settings),
        interval_seconds=settings.inventory_sync_interval_seconds,
        timeout_seconds=settings.inventory_sync_timeout_seconds,
        vcenters=[
            InventoryVCenterStatus.model_validate(row) for row in rows.mappings()
        ],
    )
