"""Read-only app configuration API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class AppConfigResponse(BaseModel):
    """Read-only retention settings (from environment)."""

    event_retention_days: int
    metric_retention_days: int
    perf_sample_interval_seconds: int
    chat_web_search_available: bool = False
    chat_attachment_images_available: bool = False
    chat_attachment_max_files: int = 0
    chat_attachment_max_file_bytes: int = 0
    chat_attachment_max_text_chars: int = 0
    mock_mode: bool = False
