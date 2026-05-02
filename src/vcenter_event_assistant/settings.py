"""Application settings (environment / .env)."""

import logging
import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LlmProvider = Literal["openai_compatible", "gemini", "copilot_cli"]


def _settings_env_file() -> str | None:
    """pytest 時（`VEA_PYTEST=1`）は `.env` を読まず、開発者の LLM キーがテストに混入しないようにする。"""
    return None if os.environ.get("VEA_PYTEST") == "1" else ".env"


def _normalize_empty_to_none(v: object) -> str | None:
    """空文字・空白のみは None に正規化する（複数の field_validator 共通）。"""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return str(v).strip() or None


class DatabaseSettingsMixin(BaseModel):
    """Database and data retention settings."""

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


class AppLogSettingsMixin(BaseModel):
    """Logging and scheduler execution settings."""

    log_level: str = Field(
        default="INFO",
        description="ルート・アプリ・uvicorn ロガーのレベル（`LOG_LEVEL`）。",
    )
    app_log_file: str | None = Field(
        default=None,
        description="アプリ（`vcenter_event_assistant`）ログのファイルパス。空はファイル出力なし（`APP_LOG_FILE`）。",
    )
    uvicorn_log_file: str | None = Field(
        default=None,
        description="uvicorn 系ログのファイルパス。空はファイル出力なし（`UVICORN_LOG_FILE`）。",
    )

    cors_origins: str = Field(default="http://localhost:5173", description="Comma-separated origins")
    vcenter_http_proxy: str | None = Field(
        default=None,
        description=(
            "vCenter 接続用 HTTP プロキシの URL（`VCENTER_HTTP_PROXY`）。"
            "例: http://proxy.example.com:8080。未設定でプロキシなし。"
        ),
    )

    scheduler_enabled: bool = Field(default=True, description="Disable for tests or one-shot runs")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """`logging` が解釈できるレベル名のみ許可する。"""
        name = v.strip().upper()
        if not name or not isinstance(getattr(logging, name, None), int):
            raise ValueError(f"無効な log_level: {v!r}（例: DEBUG, INFO, WARNING）")
        return name

    @field_validator("app_log_file", "uvicorn_log_file", mode="before")
    @classmethod
    def empty_log_path_to_none(cls, v: object) -> str | None:
        return _normalize_empty_to_none(v)

    @field_validator("vcenter_http_proxy", mode="before")
    @classmethod
    def empty_vcenter_proxy_to_none(cls, v: object) -> str | None:
        return _normalize_empty_to_none(v)


class AlertSettingsMixin(BaseModel):
    """SMTP and Alert Notifications settings."""

    smtp_host: str | None = Field(default=None, description="SMTP server host (e.g., smtp.gmail.com).")
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_use_tls: bool = Field(default=True)
    alert_email_from: str = Field(default="noreply@example.com")
    alert_email_to: str | None = Field(default=None, description="Global recipient for alerts (comma-separated).")
    alert_eval_interval_seconds: int = Field(default=60, ge=10, description="Alert evaluation job interval.")
    alert_template_firing_path: str | None = Field(default=None, description="Custom Jinja2 template for firing alerts.")
    alert_template_resolved_path: str | None = Field(default=None, description="Custom Jinja2 template for resolved alerts.")

    @field_validator(
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "alert_email_to",
        "alert_template_firing_path",
        "alert_template_resolved_path",
        mode="before",
    )
    @classmethod
    def empty_alert_settings_to_none(cls, v: object) -> str | None:
        return _normalize_empty_to_none(v)


class DigestSettingsMixin(BaseModel):
    """Event Digest scheduler and template settings."""

    digest_scheduler_enabled: bool = Field(
        default=False,
        description=(
            "（非推奨）日次ダイジェストを有効化するレガシー名。`DIGEST_SCHEDULER_ENABLED`。"
            "新設の `digest_daily_enabled` と OR で実効化される（`effective_digest_daily_enabled`）。"
        ),
    )
    digest_cron: str = Field(
        default="0 7 * * *",
        description=(
            "（非推奨）レガシー日次 cron。`DIGEST_CRON`。"
            "`digest_daily_enabled` が True のときは `digest_daily_cron` が優先され、"
            "レガシーのみ有効なときだけ本フィールドが実効（`effective_digest_daily_cron`）。"
        ),
    )

    digest_daily_enabled: bool = Field(
        default=False,
        description="日次ダイジェスト APScheduler ジョブ（`DIGEST_DAILY_ENABLED`）。",
    )
    digest_daily_cron: str = Field(
        default="0 7 * * *",
        description="日次ダイジェストの cron（`DIGEST_DAILY_CRON`、5 フィールド）。",
    )
    digest_weekly_enabled: bool = Field(
        default=False,
        description="週次ダイジェスト APScheduler ジョブ（`DIGEST_WEEKLY_ENABLED`）。",
    )
    digest_weekly_cron: str = Field(
        default="0 8 * * 0",
        description=(
            "週次ダイジェストの cron（`DIGEST_WEEKLY_CRON`、5 フィールド）。"
            "既定は毎週月曜 8:00（ローカル TZ。曜日 0）。"
            "APScheduler は曜日を Python weekday と同じに解釈する（0=月曜…6=日曜）。"
            "Unix cron の 7（日曜の別表記）は使えない。"
        ),
    )
    digest_monthly_enabled: bool = Field(
        default=False,
        description="月次ダイジェスト APScheduler ジョブ（`DIGEST_MONTHLY_ENABLED`）。",
    )
    digest_monthly_cron: str = Field(
        default="5 0 1 * *",
        description="月次ダイジェストの cron（`DIGEST_MONTHLY_CRON`）。例: 毎月 1 日 00:05 UTC。",
    )

    digest_template_path: str | None = Field(default=None)
    digest_template_dir: str | None = Field(default=None)
    digest_template_file: str = Field(default="digest.md.j2")
    digest_template_weekly_path: str | None = Field(default=None)
    digest_template_monthly_path: str | None = Field(default=None)
    digest_display_timezone: str = Field(
        default="UTC",
        description="ダイジェスト集計ウィンドウの暦境界および日時表示に用いる IANA TZ 名。",
    )

    @property
    def effective_digest_daily_enabled(self) -> bool:
        return self.digest_daily_enabled or self.digest_scheduler_enabled

    @property
    def effective_digest_daily_cron(self) -> str:
        if self.digest_daily_enabled:
            return self.digest_daily_cron
        if self.digest_scheduler_enabled:
            return self.digest_cron
        return self.digest_daily_cron


class LlmSettingsMixin(BaseModel):
    """LLM (Chat/Digest) and LangSmith settings."""

    llm_digest_provider: LlmProvider = Field(default="openai_compatible")
    llm_digest_api_key: str | None = Field(default=None)
    llm_digest_base_url: str = Field(default="https://api.openai.com/v1")
    llm_digest_model: str = Field(default="gpt-4o-mini")
    llm_digest_timeout_seconds: float = Field(default=60.0, ge=5.0, le=7200.0)

    llm_chat_provider: LlmProvider | None = Field(default=None)
    llm_chat_api_key: str | None = Field(default=None)
    llm_chat_base_url: str | None = Field(default=None)
    llm_chat_model: str | None = Field(default=None)
    llm_chat_timeout_seconds: float | None = Field(default=None, ge=5.0, le=7200.0)
    llm_chat_max_input_tokens: int = Field(default=32_000, ge=512, le=256_000)

    llm_copilot_cli_path: str | None = Field(default=None)
    llm_copilot_cli_session_auth: bool = Field(default=False)
    llm_anonymization_enabled: bool = Field(default=True)

    langsmith_tracing_enabled: bool = Field(default=False)
    langsmith_api_key: str | None = Field(default=None)
    langsmith_project: str | None = Field(default=None)
    langsmith_endpoint: str | None = Field(default=None)

    @field_validator("llm_digest_api_key", "llm_chat_api_key", "llm_chat_base_url", "llm_chat_model", mode="before")
    @classmethod
    def empty_llm_optional_str_to_none(cls, v: object) -> str | None:
        return _normalize_empty_to_none(v)

    @field_validator("llm_digest_base_url", mode="before")
    @classmethod
    def normalize_llm_digest_base_url(cls, v: object) -> str:
        if v is None:
            return "https://api.openai.com/v1"
        s = str(v).strip()
        return s or "https://api.openai.com/v1"

    @field_validator("langsmith_api_key", "langsmith_project", "langsmith_endpoint", mode="before")
    @classmethod
    def empty_langsmith_str_to_none(cls, v: object) -> str | None:
        return _normalize_empty_to_none(v)

    @field_validator("llm_copilot_cli_path", mode="before")
    @classmethod
    def empty_copilot_cli_path_to_none(cls, v: object) -> str | None:
        return _normalize_empty_to_none(v)


class Settings(
    BaseSettings,
    DatabaseSettingsMixin,
    AppLogSettingsMixin,
    AlertSettingsMixin,
    DigestSettingsMixin,
    LlmSettingsMixin,
):
    """Monolithic application settings composed of specialized mixins."""

    model_config = SettingsConfigDict(
        env_file=_settings_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
