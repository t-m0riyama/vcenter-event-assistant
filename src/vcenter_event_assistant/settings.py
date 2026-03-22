"""Application settings (environment / .env)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LlmProvider = Literal["openai_compatible", "gemini"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/vcenter_event_assistant",
        description=(
            "Async SQLAlchemy URL. Supported: "
            "PostgreSQL: postgresql+asyncpg://user:pass@host:5432/dbname; "
            "SQLite file: sqlite+aiosqlite:///./path/to/vea.db (create parent dirs as needed); "
            "SQLite memory: sqlite+aiosqlite:///:memory:"
        ),
    )

    event_poll_interval_seconds: int = Field(default=120, ge=10)
    perf_sample_interval_seconds: int = Field(default=300, ge=60)
    event_retention_days: int = Field(
        default=7,
        ge=1,
        description="Delete events older than this many days (occurred_at).",
    )
    metric_retention_days: int = Field(
        default=7,
        ge=1,
        description="Delete metric samples older than this many days (sampled_at).",
    )

    cors_origins: str = Field(default="http://localhost:5173", description="Comma-separated origins")

    scheduler_enabled: bool = Field(default=True, description="Disable for tests or one-shot runs")

    digest_scheduler_enabled: bool = Field(
        default=False,
        description="True のとき APScheduler に日次ダイジェストジョブを登録する（scheduler_enabled も True であること）。",
    )
    digest_cron: str = Field(
        default="0 7 * * *",
        description="日次ダイジェストの cron（APScheduler CronTrigger）。既定は毎日 UTC 7:00。",
    )

    llm_provider: LlmProvider = Field(
        default="openai_compatible",
        description=(
            "ダイジェストの LLM。openai_compatible は Chat Completions 互換 API、"
            "gemini は Google AI Studio（generateContent REST）。"
        ),
    )
    llm_api_key: str | None = Field(
        default=None,
        description=(
            "空のときはテンプレートのみでダイジェストを保存（外部 API を呼ばない）。"
            "OpenAI または Google AI Studio の API キー。"
        ),
    )
    llm_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="llm_provider が openai_compatible のときのみ使用（末尾は /v1 を含む想定）。",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI 互換時は gpt-4o-mini 等。Gemini 時は gemini-2.0-flash 等（Google AI Studio のモデル ID）。",
    )
    llm_timeout_seconds: float = Field(default=60.0, ge=5.0, le=600.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
