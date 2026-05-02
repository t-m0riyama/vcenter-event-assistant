from __future__ import annotations
import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

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

class ChatPreviewResponse(BaseModel):
    """チャット用プロンプトのプレビュー応答。"""
    context_block: str
    conversation: list[ChatMessage]
    llm_context: ChatLlmContextMeta | None
