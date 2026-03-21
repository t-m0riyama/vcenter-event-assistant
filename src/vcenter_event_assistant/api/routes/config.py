"""Public app configuration (non-secret)."""

from __future__ import annotations

from fastapi import APIRouter

from vcenter_event_assistant.api.schemas import AppConfigResponse
from vcenter_event_assistant.settings import get_settings

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=AppConfigResponse)
async def get_app_config() -> AppConfigResponse:
    s = get_settings()
    return AppConfigResponse(
        event_retention_days=s.event_retention_days,
        metric_retention_days=s.metric_retention_days,
    )
