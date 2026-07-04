"""Public app configuration (non-secret)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from vcenter_event_assistant.api.deps import get_app_settings
from vcenter_event_assistant.api.schemas import AppConfigResponse
from vcenter_event_assistant.settings import Settings

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=AppConfigResponse)
async def get_app_config(settings: Settings = Depends(get_app_settings)) -> AppConfigResponse:
    return AppConfigResponse(
        event_retention_days=settings.event_retention_days,
        metric_retention_days=settings.metric_retention_days,
        perf_sample_interval_seconds=settings.perf_sample_interval_seconds,
    )
