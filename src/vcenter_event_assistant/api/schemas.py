"""Pydantic schemas for API."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VCenterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    host: str = Field(min_length=1, max_length=512)
    port: int = Field(default=443, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=2048)
    is_enabled: bool = True


class VCenterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    host: str | None = Field(default=None, min_length=1, max_length=512)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=512)
    password: str | None = Field(default=None, min_length=1, max_length=2048)
    is_enabled: bool | None = None


class VCenterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    host: str
    port: int
    username: str
    is_enabled: bool
    created_at: datetime


class EventTypeGuideSnippet(BaseModel):
    """イベント種別に紐づくガイド（一覧 API で付与）。"""

    general_meaning: str | None = None
    typical_causes: str | None = None
    remediation: str | None = None
    action_required: bool = False


class EventRead(BaseModel):
    """Event row: ``occurred_at`` is normalized to UTC so JSON uses ``Z`` (JS parses as UTC)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    vcenter_id: uuid.UUID
    occurred_at: datetime
    event_type: str
    message: str
    severity: str | None
    user_name: str | None
    entity_name: str | None
    entity_type: str | None
    notable_score: int
    notable_tags: list | None
    user_comment: str | None = None
    type_guide: EventTypeGuideSnippet | None = None

    @field_validator("occurred_at", mode="before")
    @classmethod
    def occurred_at_to_utc(cls, v: object) -> datetime:
        if not isinstance(v, datetime):
            raise TypeError("occurred_at must be a datetime")
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class EventUserCommentPatch(BaseModel):
    """Update operator memo on a single event (``null`` clears the comment)."""

    user_comment: str | None = Field(..., max_length=8000)

    @field_validator("user_comment", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v


class EventListResponse(BaseModel):
    """Event list page: ``total`` matches filters before ``limit``/``offset``; ``items`` is the current page."""

    items: list[EventRead]
    total: int


class MetricPoint(BaseModel):
    """Metric sample: ``sampled_at`` is normalized to UTC so JSON uses ``Z`` (JS parses as UTC)."""

    sampled_at: datetime
    value: float
    entity_name: str
    entity_moid: str
    metric_key: str
    vcenter_id: uuid.UUID

    @field_validator("sampled_at", mode="before")
    @classmethod
    def sampled_at_to_utc(cls, v: object) -> datetime:
        if not isinstance(v, datetime):
            raise TypeError("sampled_at must be a datetime")
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class MetricSeriesResponse(BaseModel):
    """Paginated metric samples: ``total`` matches filters before ``limit``; ``points`` is capped."""

    points: list[MetricPoint]
    total: int


class MetricKeysResponse(BaseModel):
    """Distinct ``metric_key`` values present in stored samples (optionally scoped to one vCenter)."""

    metric_keys: list[str]


class HighCpuHostRow(BaseModel):
    """Dashboard summary row: ``sampled_at`` is normalized to UTC so JSON uses ``Z`` (JS parses as UTC)."""

    vcenter_id: str
    entity_name: str
    entity_moid: str
    value: float
    sampled_at: datetime

    @field_validator("sampled_at", mode="before")
    @classmethod
    def sampled_at_to_utc(cls, v: object) -> datetime:
        if not isinstance(v, datetime):
            raise TypeError("sampled_at must be a datetime")
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class HighMemHostRow(BaseModel):
    """Dashboard summary row for peak host memory usage (same shape as CPU row; separate schema type)."""

    vcenter_id: str
    entity_name: str
    entity_moid: str
    value: float
    sampled_at: datetime

    @field_validator("sampled_at", mode="before")
    @classmethod
    def sampled_at_to_utc(cls, v: object) -> datetime:
        if not isinstance(v, datetime):
            raise TypeError("sampled_at must be a datetime")
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class EventTypeCountRow(BaseModel):
    """Event type bucket: ``event_count`` is occurrences in the dashboard window (e.g. last 24h)."""

    event_type: str
    event_count: int
    max_notable_score: int
    type_guide: EventTypeGuideSnippet | None = None


class DashboardSummary(BaseModel):
    vcenter_count: int
    events_last_24h: int
    notable_events_last_24h: int
    top_notable_events: list[EventRead]
    high_cpu_hosts: list[HighCpuHostRow]
    high_mem_hosts: list[HighMemHostRow]
    top_event_types_24h: list[EventTypeCountRow]


class AppConfigResponse(BaseModel):
    """Read-only retention settings (from environment)."""

    event_retention_days: int
    metric_retention_days: int
    perf_sample_interval_seconds: int


class EventRateBucket(BaseModel):
    """UTC bucket start and event count in ``[bucket_start, bucket_start + bucket_seconds)``."""

    bucket_start: datetime
    count: int


class EventRateSeriesResponse(BaseModel):
    """Histogram of event counts per time bucket (aligned to UTC epoch boundaries)."""

    bucket_seconds: int
    buckets: list[EventRateBucket]


class EventTypesResponse(BaseModel):
    """Distinct event types for UI pickers."""

    event_types: list[str]


class EventScoreRuleCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=512)
    score_delta: int = Field(ge=-10_000, le=10_000)

    @field_validator("event_type", mode="before")
    @classmethod
    def strip_event_type(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class EventScoreRuleUpdate(BaseModel):
    score_delta: int = Field(ge=-10_000, le=10_000)


class EventScoreRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    score_delta: int


_GUIDE_TEXT_MAX = 8000


class EventTypeGuideCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=512)
    general_meaning: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    typical_causes: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    remediation: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    action_required: bool = False

    @field_validator("event_type", mode="before")
    @classmethod
    def strip_event_type(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("general_meaning", "typical_causes", "remediation", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v


class EventTypeGuideUpdate(BaseModel):
    general_meaning: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    typical_causes: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    remediation: str | None = Field(default=None, max_length=_GUIDE_TEXT_MAX)
    action_required: bool | None = None

    @field_validator("general_meaning", "typical_causes", "remediation", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v


class EventTypeGuideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    general_meaning: str | None
    typical_causes: str | None
    remediation: str | None
    action_required: bool


class EventTypeGuidesImportRequest(BaseModel):
    """一括インポート。``guides`` 内の ``event_type`` は重複不可。"""

    overwrite_existing: bool = True
    delete_guides_not_in_import: bool = False
    guides: list[EventTypeGuideCreate]


class EventTypeGuidesImportResponse(BaseModel):
    """インポート適用後のガイド件数。"""

    guides_count: int


class EventScoreRulesImportRequest(BaseModel):
    """一括インポート。``rules`` 内の ``event_type`` は重複不可。"""

    overwrite_existing: bool = True
    delete_rules_not_in_import: bool = False
    rules: list[EventScoreRuleCreate]


class EventScoreRulesImportResponse(BaseModel):
    """インポート適用後のルール件数と、再計算したイベント行数。"""

    rules_count: int
    events_updated: int


class DigestRead(BaseModel):
    """保存済みダイジェスト 1 件。時刻は UTC に正規化して JSON に ``Z`` を付与する。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    period_start: datetime
    period_end: datetime
    kind: str
    body_markdown: str
    status: str
    error_message: str | None
    llm_model: str | None
    created_at: datetime

    @field_validator("period_start", "period_end", "created_at", mode="before")
    @classmethod
    def digest_datetimes_to_utc(cls, v: object) -> datetime:
        """
        ORM からは ``datetime`` が来る想定だが、ドライバ差で ISO 文字列になる場合も UTC に正規化する。
        """
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc)
        if isinstance(v, str):
            s = v.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        raise TypeError("expected datetime or ISO-8601 string")


class DigestListResponse(BaseModel):
    items: list[DigestRead]
    total: int


class ChatMessage(BaseModel):
    """チャット 1 ターン（クライアント送受信・LLM 呼び出しの両方で使用）。"""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=200_000)


class ChatRequest(BaseModel):
    """期間指定チャット。JSON では ``from`` / ``to`` キー（クエリと同様の別名）。"""

    model_config = ConfigDict(populate_by_name=True)

    from_time: datetime = Field(alias="from")
    to_time: datetime = Field(alias="to")
    messages: list[ChatMessage] = Field(min_length=1)
    vcenter_id: uuid.UUID | None = None
    top_notable_min_score: int = Field(default=1, ge=0, le=100)
    include_cpu_event_correlation: bool = Field(
        default=False,
        description="真のときのみ高 CPU 近傍イベントの追加 DB 集計を行い LLM コンテキストにマージする（負荷あり）",
    )
    cpu_correlation_threshold_pct: float = Field(default=85.0, ge=0.0, le=100.0)
    cpu_correlation_window_minutes: int = Field(default=15, ge=1, le=180)

    @model_validator(mode="after")
    def last_message_is_user(self) -> ChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("最後のメッセージは user である必要があります")
        return self


class ChatLlmContextMeta(BaseModel):
    """チャット LLM 直前のコンテキスト統計（トークン予算・JSON 切り詰めの確認用）。"""

    json_truncated: bool = Field(description="マージ済み JSON がトークン上限のため切り詰められたか")
    estimated_input_tokens: int = Field(
        description="tiktoken cl100k_base による入力全体の推定トークン数（Gemini 公式値とは一致しない場合あり）"
    )
    max_input_tokens: int = Field(description="設定上の上限（LLM_CHAT_MAX_INPUT_TOKENS）")
    message_turns: int = Field(description="上限適用後の会話ターン数")


class ChatResponse(BaseModel):
    """チャット API の応答。LLM 失敗時は ``assistant_content`` が空で ``error`` に理由。"""

    assistant_content: str
    error: str | None = None
    llm_context: ChatLlmContextMeta | None = Field(
        default=None,
        description="LLM を呼んだ直前のコンテキスト統計。API キーが空でスキップしたときは None。",
    )


class DigestRunRequest(BaseModel):
    """手動ダイジェスト実行。``from_time`` / ``to_time`` を省略すると ``DIGEST_DISPLAY_TIMEZONE`` に基づく直前期間を対象とする（日次=直前暦日、週次=直前週、月次=直前月）。"""

    kind: str = Field(
        default="daily",
        max_length=64,
        description=(
            "daily / weekly / monthly（大文字小文字は区別しない）。"
            "期間省略時はこの種別に応じた集計ウィンドウ（設定 TZ の暦）を使う。"
        ),
    )
    from_time: datetime | None = None
    to_time: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self) -> DigestRunRequest:
        if (self.from_time is None) != (self.to_time is None):
            raise ValueError("from_time と to_time は両方指定するか、両方省略してください")
        if self.from_time is not None and self.to_time is not None and self.from_time >= self.to_time:
            raise ValueError("from_time は to_time より前である必要があります")
        return self
