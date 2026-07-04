from __future__ import annotations
import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from vcenter_event_assistant.services.chat.chat_incident_timeline import IncidentTimelinePayload

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
    include_period_metrics_cpu: bool = Field(
        default=False,
        description="真のとき期間内 CPU 使用率をバケット平均で LLM コンテキストに含める（追加 DB クエリ）",
    )
    include_period_metrics_memory: bool = Field(
        default=False,
        description="真のとき期間内メモリ使用率をバケット平均で含める",
    )
    include_period_metrics_disk_io: bool = Field(
        default=False,
        description="真のとき期間内ディスク IO 系メトリクスをバケット平均で含める",
    )
    include_period_metrics_network_io: bool = Field(
        default=False,
        description="真のとき期間内ネットワーク IO 系メトリクスをバケット平均で含める",
    )
    metric_threshold_cpu_pct: float | None = Field(default=None, ge=0, le=100)
    metric_threshold_memory_pct: float | None = Field(default=None, ge=0, le=100)
    metric_threshold_disk_pct: float | None = Field(default=None, ge=0, le=100)
    metric_threshold_network_pct: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def last_message_is_user(self) -> ChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("最後のメッセージは user である必要があります")
        return self


class IncidentTimelineGraphCapturedRange(BaseModel):
    """グラフ表示に用いた期間（ビューポート）の任意スナップショット。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_time: datetime = Field(alias="from")
    to_time: datetime = Field(alias="to")


class IncidentTimelineGraphContext(BaseModel):
    """手動スナップショットに付与するメトリクス再生用メタデータ（すべて任意）。"""

    model_config = ConfigDict(extra="forbid")

    metric_key: str | None = Field(default=None, max_length=512)
    chart_event_type: str | None = Field(default=None, max_length=512)
    marker_timestamp_utc: datetime | None = None
    vcenter_id: uuid.UUID | None = None
    captured_range: IncidentTimelineGraphCapturedRange | None = None


class IncidentTimelineBuildRequest(BaseModel):
    """インシデントタイムライン構築用リクエスト。messages は受け付けない。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_time: datetime = Field(alias="from")
    to_time: datetime = Field(alias="to")
    vcenter_id: uuid.UUID | None = None
    top_notable_min_score: int = Field(default=1, ge=0, le=100)
    alert_top_n: int = Field(default=3, ge=1, le=20)
    include_period_metrics_cpu: bool = Field(
        default=False,
        description="真のとき期間内 CPU 使用率をバケット平均で LLM コンテキストに含める（追加 DB クエリ）",
    )
    include_period_metrics_memory: bool = Field(
        default=False,
        description="真のとき期間内メモリ使用率をバケット平均で含める",
    )
    include_period_metrics_disk_io: bool = Field(
        default=False,
        description="真のとき期間内ディスク IO 系メトリクスをバケット平均で含める",
    )
    include_period_metrics_network_io: bool = Field(
        default=False,
        description="真のとき期間内ネットワーク IO 系メトリクスをバケット平均で含める",
    )
    metric_threshold_cpu_pct: float | None = Field(default=None, ge=0, le=100)
    metric_threshold_memory_pct: float | None = Field(default=None, ge=0, le=100)
    metric_threshold_disk_pct: float | None = Field(default=None, ge=0, le=100)
    metric_threshold_network_pct: float | None = Field(default=None, ge=0, le=100)


class IncidentTimelineManualSnapshotCreateRequest(BaseModel):
    """手動スナップショット保存リクエスト。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_time: datetime = Field(alias="from")
    to_time: datetime = Field(alias="to")
    timestamp_utc: datetime
    operator_note: str = Field(min_length=1, max_length=10_000)
    build_request_payload: IncidentTimelineBuildRequest | None = None
    graph_context: IncidentTimelineGraphContext | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> IncidentTimelineManualSnapshotCreateRequest:
        if self.from_time >= self.to_time:
            raise ValueError("from は to より前である必要があります")
        note = self.operator_note.strip()
        if note == "":
            raise ValueError("operator_note は空白のみを許可しません")
        self.operator_note = note
        return self


class IncidentTimelineManualSnapshotCreateResponse(BaseModel):
    """手動スナップショット保存レスポンス。"""

    snapshot_id: str
    operator_note: str
    timestamp_utc: datetime
    build_request_payload: IncidentTimelineBuildRequest
    snapshot_kind: Literal["manual", "auto"] = "manual"
    trigger_id: str | None = None
    graph_context: IncidentTimelineGraphContext | None = None


class IncidentTimelineManualSnapshotListItem(BaseModel):
    """手動スナップショット一覧の1件。"""
    model_config = ConfigDict(populate_by_name=True)

    snapshot_id: str
    from_time: datetime = Field(alias="from")
    to_time: datetime = Field(alias="to")
    operator_note: str
    timestamp_utc: datetime
    build_request_payload: IncidentTimelineBuildRequest
    snapshot_kind: Literal["manual", "auto"] = "manual"
    trigger_id: str | None = None
    trigger_evidence: dict[str, object] | None = None
    graph_context: IncidentTimelineGraphContext | None = None


class IncidentTimelineManualSnapshotListResponse(BaseModel):
    """手動スナップショット一覧レスポンス。"""

    items: list[IncidentTimelineManualSnapshotListItem]
    total: int
    limit: int
    offset: int

class ChatLlmContextMeta(BaseModel):
    """チャット LLM 直前のコンテキスト統計（トークン予算・JSON 切り詰めの確認用）。"""
    json_truncated: bool = Field(description="マージ済み JSON がトークン上限のため切り詰められたか")
    estimated_input_tokens: int = Field(
        description="tiktoken cl100k_base による入力全体の推定トークン数（Gemini 公式値とは一致しない場合あり）"
    )
    max_input_tokens: int = Field(description="設定上の上限（LLM_CHAT_MAX_INPUT_TOKENS）")
    message_turns: int = Field(description="上限適用後の会話ターン数")

class TriggerEvidence(BaseModel):
    """監査説明に用いるトリガー根拠の最小情報。"""

    trigger_type: str = Field(
        min_length=1,
        max_length=128,
        description="根拠の種別（例: alert_rule / timeline_item）",
    )
    summary: str = Field(
        min_length=1,
        max_length=4000,
        description="回答を生成した直接根拠の要約文",
    )
    source_id: str | None = Field(
        default=None,
        description="関連ルールやエンティティの識別子（未特定時は null）",
    )

class ChatResponse(BaseModel):
    """チャット API の応答。LLM 失敗時は ``assistant_content`` が空で ``error`` に理由。"""
    assistant_content: str
    error: str | None = None
    llm_context: ChatLlmContextMeta | None = Field(
        default=None,
        description="LLM を呼んだ直前のコンテキスト統計。API キーが空でスキップしたときは None。",
    )
    created_at: datetime | None = Field(
        default=None,
        description="応答時刻",
    )
    latency_ms: int | None = Field(
        default=None,
        description="最初の一文字が生成されるまでの時間(ms)",
    )
    token_per_sec: float | None = Field(
        default=None,
        description="トークン生成速度",
    )
    trigger_evidence: TriggerEvidence | None = Field(
        default=None,
        description="回答のトリガー根拠。旧保存データとの互換のため省略/ null を許容。",
    )

class ChatPreviewResponse(BaseModel):
    """チャット用プロンプトのプレビュー応答。"""
    context_block: str
    conversation: list[ChatMessage]
    llm_context: ChatLlmContextMeta | None
    incident_timeline: IncidentTimelinePayload | None = None
