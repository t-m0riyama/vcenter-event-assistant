"""タイムライン画面専用 API（``POST /api/incident-timeline/view``）のスキーマ。

チャットの LLM 用集計（``IncidentTimelineBuildRequest`` 系）とは別物で、個々の出来事と
それを辿るための参照（``ref``）を返す。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vcenter_event_assistant.api.schemas.base import UtcDateTime, to_utc_or_value_error
from vcenter_event_assistant.services.event_patterns.definitions import PatternLevel

TimelineSource = Literal["event", "alert", "metric", "log"]
TimelineLevel = Literal["critical", "error", "warning", "info"]

_ALL_SOURCES: tuple[TimelineSource, ...] = ("event", "alert", "metric", "log")
# IncidentTimelineBuildRequest と同じ上限。
_MAX_SPAN = timedelta(days=90)


def _default_sources() -> list[TimelineSource]:
    return list(_ALL_SOURCES)


def normalize_time_span(from_time: datetime, to_time: datetime) -> tuple[datetime, datetime]:
    """期間の from/to を UTC に揃えて検証し、揃えた組を返す（from が to より前で、幅が 90 日以内）。

    タイムゾーンの無い値は UTC とみなす。満たさなければ ``ValueError`` を投げる。
    """
    try:
        ft = to_utc_or_value_error(from_time)
        tt = to_utc_or_value_error(to_time)
    except ValueError as exc:
        # model_validator から呼ぶのでエラーの loc は ["body"] になる。どの項目かを文言で示す。
        raise ValueError("from and to must be within the supported datetime range in UTC") from exc
    if ft >= tt:
        raise ValueError("from must be before to")
    if tt - ft > _MAX_SPAN:
        raise ValueError("time range must not exceed 90 days")
    return ft, tt


class IncidentTimelineViewRequest(BaseModel):
    """タイムライン表示用リクエスト。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_time: datetime = Field(alias="from")
    to_time: datetime = Field(alias="to")
    vcenter_id: uuid.UUID | None = None
    entity: str | None = Field(
        default=None,
        max_length=1024,
        description="対象名の部分一致（大文字小文字を区別しない）。moid 指定時は moid の無い行の対象名（完全一致）",
    )
    entity_moid: str | None = Field(default=None, max_length=256, description="対象の moid（vcenter_id が必要）")
    anchor_time: UtcDateTime | None = Field(default=None, alias="anchor")
    min_score: int = Field(default=1, ge=0, le=100)
    sources: list[TimelineSource] = Field(default_factory=_default_sources, min_length=1)
    metric_threshold_cpu_pct: float = Field(default=80.0, ge=0, le=100)
    metric_threshold_memory_pct: float = Field(default=85.0, ge=0, le=100)
    metric_threshold_disk_pct: float = Field(
        default=75.0,
        ge=0,
        le=100,
        description=(
            "互換のために受け取るが使わない。ディスク系の指標は値が KB/s（host.disk.usage_kbps は vSphere の "
            "disk.usage.average で単位は KBps）なので、% の閾値を当てられない。"
        ),
    )
    metric_threshold_network_pct: float = Field(
        default=75.0,
        ge=0,
        le=100,
        description=(
            "互換のために受け取るが使わない。ネットワーク系の指標は値が KB/s なので、% の閾値を当てられない。"
        ),
    )
    item_limit: int = Field(default=500, ge=1, le=1000)

    @field_validator("entity", "entity_moid", mode="before")
    @classmethod
    def _normalize_entity(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("sources")
    @classmethod
    def _dedupe_sources(cls, value: list[TimelineSource]) -> list[TimelineSource]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_time_span(self) -> IncidentTimelineViewRequest:
        if self.entity_moid is not None and self.vcenter_id is None:
            raise ValueError("vcenter_id is required when entity_moid is specified")
        self.from_time, self.to_time = normalize_time_span(self.from_time, self.to_time)
        return self


class IncidentTimelineSavedViewRequest(BaseModel):
    """保存済みスナップショットの ``view_request`` を応答に載せるための読み取り用モデル。

    保存時は ``IncidentTimelineViewRequest`` で厳しく検証するが、読むときは将来の項目の増減や
    範囲の検査の変更で結果ごと読めなくならないよう、未知の項目を無視し、範囲などの検査をしない。
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    from_time: datetime = Field(alias="from")
    to_time: datetime = Field(alias="to")
    vcenter_id: uuid.UUID | None = None
    entity: str | None = None
    entity_moid: str | None = None
    anchor_time: datetime | None = Field(default=None, alias="anchor")
    min_score: int | None = None
    sources: list[str] | None = None
    metric_threshold_cpu_pct: float | None = None
    metric_threshold_memory_pct: float | None = None
    metric_threshold_disk_pct: float | None = None
    metric_threshold_network_pct: float | None = None
    item_limit: int | None = None


class IncidentTimelineItemRef(BaseModel):
    """元レコードへの参照。種別に当てはまらない項目は None。"""

    event_id: int | None = None
    event_type: str | None = None
    alert_history_id: int | None = None
    alert_rule_id: int | None = None
    alert_rule_name: str | None = None
    alert_rule_type: str | None = None
    alert_state: str | None = None
    metric_key: str | None = None
    entity_moid: str | None = None
    log_id: int | None = None
    # 以下はメトリクスの超過区間（kind="metric"）の行でだけ入る。
    threshold_pct: float | None = Field(default=None, description="当てた閾値（%）")
    peak_value: float | None = Field(default=None, description="期間内の区間のピーク値（%）")
    peak_at_utc: datetime | None = Field(default=None, description="ピークのサンプルの時刻（同じ値なら早いほう）")
    sample_count: int | None = Field(default=None, description="期間内の区間のサンプル数")
    continues_from_before: bool | None = Field(
        default=None, description="期間の開始前から超過が続いているか"
    )
    continues_after: bool | None = Field(
        default=None,
        description=(
            "期間の終わりでも超過が続いているか。系列の期間内の最後のサンプルが閾値以上で、期間の終わり"
            "（to が未来なら現在時刻）から区間をつなぐ間隔の上限以内にあるとき真。期間の後ろのサンプルは読まない"
        ),
    )


class IncidentTimelineViewItem(BaseModel):
    """時系列リストの 1 行（個別の出来事、または連続する同種のまとまり）。"""

    id: str = Field(description="レスポンス内で一意（例: event:123, alert:45）")
    kind: TimelineSource
    timestamp_utc: datetime
    end_utc: datetime | None = None
    level: TimelineLevel
    title: str
    detail: str | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    vcenter_id: uuid.UUID | None = None
    vcenter_name: str | None = None
    score: int | None = None
    count: int = Field(default=1, ge=1)
    ref: IncidentTimelineItemRef = Field(default_factory=IncidentTimelineItemRef)
    config_change_kind: str | None = None


class IncidentTimelineOverviewBucket(BaseModel):
    """俯瞰グラフ 1 本分の件数。"""

    bucket_start_utc: datetime
    event_total: int = Field(ge=0)
    event_notable: int = Field(ge=0)
    alert: int = Field(ge=0)
    metric_breach: int = Field(ge=0)
    log_error: int = Field(ge=0)


class IncidentTimelineTopEntity(BaseModel):
    """出来事の多い対象。vCenter ごとに moid または名前で数える。"""

    entity_name: str
    entity_moid: str | None = None
    entity_type: str | None = None
    vcenter_id: uuid.UUID | None = None
    vcenter_name: str | None = None
    item_count: int
    first_seen_utc: datetime


class IncidentTimelineNewEventType(BaseModel):
    event_type: str
    count: int
    first_seen_utc: datetime
    max_score: int


class IncidentTimelineDetectedPattern(BaseModel):
    pattern_id: str
    title: str
    description: str
    level: PatternLevel
    vcenter_id: uuid.UUID
    vcenter_name: str | None = None
    entity_moid: str
    entity_name: str | None = None
    entity_type: str | None = None
    first_utc: datetime
    last_utc: datetime
    event_count: int
    event_ids: list[int]


class IncidentTimelineConfigChange(BaseModel):
    """関連するイベントとタスクをまとめた構成変更。"""

    kind: str
    label: str
    first_utc: datetime
    last_utc: datetime
    vcenter_id: uuid.UUID | None = None
    vcenter_name: str | None = None
    entity_name: str | None = None
    entity_moid: str | None = None
    entity_type: str | None = None
    user_names: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    event_count: int = 0
    event_ids: list[int] = Field(default_factory=list)


class IncidentTimelineNewLogPattern(BaseModel):
    vcenter_id: uuid.UUID
    vcenter_name: str
    pattern_key: str
    log_kind: str
    template: str
    count: int
    first_utc: UtcDateTime
    max_severity_rank: int
    hosts: list[str]
    first_seen_at: UtcDateTime
    warning_first_seen_at: UtcDateTime


class IncidentTimelineLogPatternWarmup(BaseModel):
    vcenter_id: uuid.UUID
    vcenter_name: str
    source_id: str | None
    host: str | None
    log_kind: str
    warmup_ends_at: UtcDateTime | None


class IncidentTimelineHighlights(BaseModel):
    first_signal: IncidentTimelineViewItem | None = None
    top_entities: list[IncidentTimelineTopEntity] = Field(default_factory=list)
    new_event_types: list[IncidentTimelineNewEventType] = Field(default_factory=list)
    new_log_patterns: list[IncidentTimelineNewLogPattern] | None = None
    new_log_patterns_total: int = 0
    log_patterns_backfill_pending: bool = False
    log_patterns_warming_up: list[IncidentTimelineLogPatternWarmup] = Field(default_factory=list)
    log_patterns_warming_up_total: int = 0
    new_log_patterns_out_of_retention: bool = Field(
        default=False,
        description="期間の始まりがログの保持期間より前で、行が削除された型は一覧に出ないことがある",
    )
    detected_patterns: list[IncidentTimelineDetectedPattern] = Field(default_factory=list)
    detected_patterns_total: int = 0
    omitted_patterns: list[str] = Field(default_factory=list)
    config_changes: list[IncidentTimelineConfigChange] | None = None
    config_changes_total: int = 0
    config_change_counts: dict[str, int] = Field(default_factory=dict)
    config_changes_truncated: bool = False


class IncidentTimelineOmittedSource(BaseModel):
    """一覧から省いた種別と、その理由。"""

    source: Literal["metric", "log"]
    reason: Literal["too_many_rows"] = Field(
        description="too_many_rows: 行数が上限（CONTEXT_AGGREGATION_MAX_ROWS）を超えた"
    )


class IncidentTimelineViewResponse(BaseModel):
    from_utc: datetime
    to_utc: datetime
    anchor_utc: datetime | None = None
    bucket_seconds: int
    overview: list[IncidentTimelineOverviewBucket]
    items: list[IncidentTimelineViewItem]
    truncated: bool
    total_items: int = Field(description="打ち切り前の件数")
    config_change_items_total: int = 0
    config_change_items_shown: int = 0
    config_change_items_truncated: bool = False
    highlights: IncidentTimelineHighlights
    omitted_sources: list[IncidentTimelineOmittedSource] = Field(
        default_factory=list,
        description=(
            "行数が上限を超えたため、一覧（items）とハイライトから省いた種別（metric / log）。"
            "log の俯瞰の件数（log_error）は返す。metric の俯瞰（metric_breach）は区間を作れないので 0 になり、"
            "実際の件数は分からない。省いていなければ空の配列。"
        ),
    )
