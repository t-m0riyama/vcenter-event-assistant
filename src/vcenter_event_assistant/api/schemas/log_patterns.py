"""ログの型ごとの集計の応答。"""

from uuid import UUID

from pydantic import BaseModel

from vcenter_event_assistant.api.schemas.base import UtcDateTime


class LogPatternRead(BaseModel):
    vcenter_id: UUID
    vcenter_name: str
    pattern_key: str
    log_kind: str
    template: str
    count: int
    first_utc: UtcDateTime
    last_utc: UtcDateTime
    max_severity_rank: int
    first_seen_at: UtcDateTime


class LogPatternsResponse(BaseModel):
    items: list[LogPatternRead]
    total: int
    truncated: bool
    pending_count: int
