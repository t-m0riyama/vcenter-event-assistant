"""logging ファイル出力のスモークテスト。"""

from __future__ import annotations

import logging


def test_app_and_uvicorn_logs_written_to_separate_files(tmp_path, monkeypatch) -> None:
    """APP_LOG_FILE / UVICORN_LOG_FILE が設定されているとき、それぞれのファイルへ出力される。"""
    app_log = tmp_path / "app.log"
    uv_log = tmp_path / "uvicorn.log"
    monkeypatch.setenv("APP_LOG_FILE", str(app_log))
    monkeypatch.setenv("UVICORN_LOG_FILE", str(uv_log))
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    from vcenter_event_assistant.main import create_app
    from vcenter_event_assistant.settings import get_settings

    get_settings.cache_clear()
    create_app()

    logging.getLogger("vcenter_event_assistant.smoke").info("line-app")
    logging.getLogger("uvicorn.access").info("line-access")

    for h in logging.getLogger("vcenter_event_assistant.smoke").handlers:
        h.flush()
    for h in logging.getLogger("uvicorn.access").handlers:
        h.flush()

    app_text = app_log.read_text(encoding="utf-8")
    uv_text = uv_log.read_text(encoding="utf-8")
    assert "line-app" in app_text
    assert "line-app" not in uv_text
    assert "line-access" in uv_text
    assert "line-access" not in app_text
