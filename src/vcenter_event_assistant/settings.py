"""Application settings (environment / .env)."""

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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
        """空文字・空白のみは None に正規化する。"""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s or None
        return str(v).strip() or None

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

    digest_template_path: str | None = Field(
        default=None,
        description=(
            "非空のとき最優先でこのファイルを Jinja2 テンプレとして読む（UTF-8）。"
            "存在しない・読めない場合はエラーとし、DIGEST_TEMPLATE_DIR にはフォールバックしない。"
            "相対パスはプロセスのカレントディレクトリ基準。"
        ),
    )
    digest_template_dir: str | None = Field(
        default=None,
        description=(
            "DIGEST_TEMPLATE_PATH が空のとき、DIGEST_TEMPLATE_FILE と結合してテンプレパスを構成する。"
            "ファイルが存在しない場合はエラー（同梱テンプレにはフォールバックしない）。"
        ),
    )
    digest_template_file: str = Field(
        default="digest.md.j2",
        description="digest_template_dir と併用するファイル名。",
    )
    digest_template_weekly_path: str | None = Field(
        default=None,
        description=(
            "任意。非空かつダイジェストの kind が weekly のとき、このファイルを "
            "DIGEST_TEMPLATE_PATH / DIGEST_TEMPLATE_DIR より優先して読む（UTF-8）。"
            "ファイルが存在しない場合はエラー。空のときは通常のテンプレ解決にフォールバック。"
        ),
    )
    digest_template_monthly_path: str | None = Field(
        default=None,
        description=(
            "任意。非空かつ kind が monthly のとき、同様に最優先で読む。"
            "ファイルが存在しない場合はエラー。空のときは通常解決にフォールバック。"
        ),
    )
    digest_display_timezone: str = Field(
        default="UTC",
        description=(
            "ダイジェスト本文の日時表示および日次・週次・月次の集計ウィンドウの暦境界に用いる IANA タイムゾーン名（例: Asia/Tokyo）。"
            "無効な名前は UTC にフォールバックし警告ログを出す。"
        ),
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
    llm_timeout_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=7200.0,
        description=(
            "httpx の読み取りタイムアウト（秒）。ローカル Ollama は長いプロンプトで数分〜かかることがある。"
            "値を変えたらプロセス再起動が必要（get_settings が lru_cache のため）。"
        ),
    )
    llm_chat_max_input_tokens: int = Field(
        default=32_000,
        ge=512,
        le=256_000,
        description=(
            "チャット LLM の入力全体の目安トークン上限（tiktoken cl100k_base で推定。"
            "Gemini 公式のトークン数と一致しない場合がある（`LLM_CHAT_MAX_INPUT_TOKENS`）。"
        ),
    )

    langsmith_tracing_enabled: bool = Field(
        default=False,
        description="LangSmith へ LLM トレースを送る（`LANGSMITH_TRACING_ENABLED`）。既定は無効。",
    )
    langsmith_api_key: str | None = Field(
        default=None,
        description="LangSmith API キー（`LANGSMITH_API_KEY`）。空ならトレース用コールバックは付与しない。",
    )
    langsmith_project: str | None = Field(
        default=None,
        description="LangSmith プロジェクト名（`LANGSMITH_PROJECT`）。空ならクライアント既定。",
    )
    langsmith_endpoint: str | None = Field(
        default=None,
        description="LangSmith API ベース URL（`LANGSMITH_ENDPOINT`）。空なら SDK 既定。",
    )

    @field_validator("langsmith_api_key", "langsmith_project", "langsmith_endpoint", mode="before")
    @classmethod
    def empty_langsmith_str_to_none(cls, v: object) -> str | None:
        """空文字・空白のみは None に正規化する。"""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s or None
        return str(v).strip() or None

    @property
    def effective_digest_daily_enabled(self) -> bool:
        """日次ダイジェストジョブを登録するか（新フラグとレガシーの OR）。"""
        return self.digest_daily_enabled or self.digest_scheduler_enabled

    @property
    def effective_digest_daily_cron(self) -> str:
        """日次ジョブ用の実効 cron（新 `digest_daily_enabled` 優先、なければレガシー `digest_cron`）。"""
        if self.digest_daily_enabled:
            return self.digest_daily_cron
        if self.digest_scheduler_enabled:
            return self.digest_cron
        return self.digest_daily_cron


@lru_cache
def get_settings() -> Settings:
    return Settings()
