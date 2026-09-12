"""Read-only collector plugin status API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas.plugins import (
    CollectorRunStatusRead,
    CollectorStatusListResponse,
    CollectorStatusRead,
)
from vcenter_event_assistant.db.models import CollectorRunState, VCenter
from vcenter_event_assistant.plugins.registry import get_collector_registry

router = APIRouter(prefix="/plugins/collectors", tags=["plugins"])


@router.get("", response_model=CollectorStatusListResponse)
async def list_collectors(
    session: AsyncSession = Depends(get_session),
) -> CollectorStatusListResponse:
    registry = get_collector_registry()
    result = await session.execute(
        select(CollectorRunState, VCenter.name)
        .join(VCenter, VCenter.id == CollectorRunState.vcenter_id)
        .order_by(
            CollectorRunState.collector_id.asc(),
            VCenter.name.asc(),
            CollectorRunState.vcenter_id.asc(),
        )
    )
    by_plugin: dict[str, list[CollectorRunStatusRead]] = {}
    for state, vcenter_name in result.all():
        by_plugin.setdefault(state.collector_id, []).append(
            CollectorRunStatusRead(
                vcenter_id=state.vcenter_id,
                vcenter_name=vcenter_name,
                status=state.status,
                collector_version=state.collector_version,
                last_started_at=state.last_started_at,
                last_success_at=state.last_success_at,
                last_failure_at=state.last_failure_at,
                events_inserted=state.events_inserted,
                metrics_inserted=state.metrics_inserted,
                error=state.error_message,
            )
        )
    collectors: list[CollectorStatusRead] = []
    for registration in sorted(
        registry.registrations.values(), key=lambda item: item.plugin_id
    ):
        manifest = registration.plugin.manifest if registration.plugin else None
        collectors.append(
            CollectorStatusRead(
                id=registration.plugin_id,
                display_name=manifest.display_name if manifest else None,
                source=registration.source,
                status=registration.status,
                error=registration.error,
                version=manifest.version if manifest else None,
                api_version=manifest.api_version if manifest else None,
                data_kinds=sorted(manifest.data_kinds) if manifest else [],
                interval_seconds=registration.config.interval_seconds
                if registration.config
                else None,
                timeout_seconds=registration.config.timeout_seconds
                if registration.config
                else None,
                runs=by_plugin.get(registration.plugin_id, []),
            )
        )
    return CollectorStatusListResponse(
        generation=registry.generation, collectors=collectors
    )
