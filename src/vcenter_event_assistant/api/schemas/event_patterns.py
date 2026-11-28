"""組み込みの障害パターンの一覧 API のスキーマ。"""

from pydantic import BaseModel

from vcenter_event_assistant.services.event_patterns.definitions import PatternKind, PatternLevel, PatternSubject


class EventPatternStepRead(BaseModel):
    event_types: list[str]


class EventPatternRead(BaseModel):
    id: str
    title: str
    description: str
    level: PatternLevel
    kind: PatternKind
    steps: list[EventPatternStepRead]
    within_minutes: int
    min_count: int | None
    subject: PatternSubject | None = None
