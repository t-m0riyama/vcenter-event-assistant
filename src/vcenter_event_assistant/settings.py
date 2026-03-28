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
        description="週次ダイジェストの cron（`DIGEST_WEEKLY_CRON`）。曜日は環境により 0 または 7 が日曜のことがある。",
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
            "ダイジェスト本文の日時表示に用いる IANA タイムゾーン名（例: Asia/Tokyo）。"
            "無効な名前は UTC にフォールバックし警告ログを出す。集計ウィンドウ自体は従来どおり UTC。"
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
    llm_timeout_seconds: float = Field(default=60.0, ge=5.0, le=600.0)

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
