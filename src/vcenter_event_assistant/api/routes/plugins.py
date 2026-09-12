"""Read-only collector plugin status API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.db.models import CollectorRunState
from vcenter_event_assistant.plugins.registry import get_collector_registry

router = APIRouter(prefix="/plugins/collectors", tags=["plugins"])


@router.get("")
async def list_collectors(
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    registry = get_collector_registry()
    states = list((await session.execute(select(CollectorRunState))).scalars().all())
    by_plugin: dict[str, list[dict[str, object]]] = {}
    for state in states:
        by_plugin.setdefault(state.collector_id, []).append(
            {
                "vcenter_id": str(state.vcenter_id),
                "status": state.status,
                "collector_version": state.collector_version,
                "last_started_at": state.last_started_at,
                "last_success_at": state.last_success_at,
                "last_failure_at": state.last_failure_at,
                "events_inserted": state.events_inserted,
                "metrics_inserted": state.metrics_inserted,
                "error": state.error_message,
            }
        )
    collectors = []
    for registration in registry.registrations.values():
        manifest = registration.plugin.manifest if registration.plugin else None
        collectors.append(
            {
                "id": registration.plugin_id,
                "source": registration.source,
                "status": registration.status,
                "error": registration.error,
                "version": manifest.version if manifest else None,
                "api_version": manifest.api_version if manifest else None,
                "interval_seconds": registration.config.interval_seconds
                if registration.config
                else None,
                "runs": by_plugin.get(registration.plugin_id, []),
            }
        )
    return {"generation": registry.generation, "collectors": collectors}
