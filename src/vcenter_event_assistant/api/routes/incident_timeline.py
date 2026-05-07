"""インシデントタイムライン専用 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas.chat import IncidentTimelineBuildRequest
from vcenter_event_assistant.services.chat_context_payloads import build_incident_timeline_payload
from vcenter_event_assistant.services.chat_incident_timeline import IncidentTimelinePayload

router = APIRouter(prefix="/incident-timeline", tags=["incident-timeline"])


@router.post("", response_model=IncidentTimelinePayload)
async def post_incident_timeline(
    body: IncidentTimelineBuildRequest,
    session: AsyncSession = Depends(get_session),
) -> IncidentTimelinePayload:
    return await build_incident_timeline_payload(session, body)
