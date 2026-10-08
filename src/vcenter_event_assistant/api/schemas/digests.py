"""Digest API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vcenter_event_assistant.api.schemas.base import _normalize_to_utc


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
        return _normalize_to_utc(v)


class DigestListResponse(BaseModel):
    items: list[DigestRead]
    total: int


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
