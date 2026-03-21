"""Public app configuration (non-secret)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from vcenter_event_assistant.api.schemas import AppConfigResponse
from vcenter_event_assistant.auth.dependencies import require_auth
from vcenter_event_assistant.settings import get_settings

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=AppConfigResponse)
async def get_app_config(_: None = Depends(require_auth)) -> AppConfigResponse:
    s = get_settings()
    return AppConfigResponse(
        event_retention_days=s.event_retention_days,
        metric_retention_days=s.metric_retention_days,
    )
