"""Read-only app configuration API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class AppConfigResponse(BaseModel):
    """Read-only retention settings (from environment)."""

    event_retention_days: int
    metric_retention_days: int
    perf_sample_interval_seconds: int
    chat_web_search_available: bool = False
