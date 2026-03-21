"""Application settings (environment / .env)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    auth_bearer_token: str | None = Field(default=None, description="If set, require Authorization: Bearer")
    auth_basic_username: str | None = Field(default=None)
    auth_basic_password: str | None = Field(default=None)

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
