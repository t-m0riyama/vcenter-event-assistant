"""組み込みの障害パターンの一覧。"""

from fastapi import APIRouter

from vcenter_event_assistant.api.auth_deps import RequireViewer
from vcenter_event_assistant.api.schemas.event_patterns import EventPatternRead, EventPatternStepRead
from vcenter_event_assistant.services.event_patterns.definitions import BUILTIN_PATTERNS

router = APIRouter(prefix="/event-patterns", tags=["event-patterns"])


@router.get("", dependencies=[RequireViewer], response_model=list[EventPatternRead])
async def list_event_patterns() -> list[EventPatternRead]:
    return [
        EventPatternRead(
            id=pattern.id,
            title=pattern.title,
            description=pattern.description,
            level=pattern.level,
            kind=pattern.kind,
            steps=[EventPatternStepRead(event_types=sorted(step.event_types)) for step in pattern.steps],
            within_minutes=pattern.within_minutes,
            min_count=pattern.min_count,
        )
        for pattern in BUILTIN_PATTERNS
    ]
