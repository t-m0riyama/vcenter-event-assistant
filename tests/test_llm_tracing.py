"""llm_tracing.build_llm_runnable_config の単体テスト。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from vcenter_event_assistant.services.llm_tracing import build_llm_runnable_config
from vcenter_event_assistant.settings import Settings


def test_build_llm_runnable_config_off_has_tags_and_metadata_no_callbacks() -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        langsmith_tracing_enabled=False,
        langsmith_api_key=None,
    )
    cfg = build_llm_runnable_config(
        s,
        run_kind="period_chat",
        vcenter_id="vc-1",
    )
    assert cfg is not None
    assert "vea" in (cfg.get("tags") or [])
    assert "period_chat" in (cfg.get("tags") or [])
    assert cfg.get("metadata", {}).get("run_kind") == "period_chat"
    assert cfg.get("metadata", {}).get("vcenter_id") == "vc-1"
    assert cfg.get("callbacks") in (None, [])


@patch("vcenter_event_assistant.services.llm_tracing.LangChainTracer")
@patch("vcenter_event_assistant.services.llm_tracing.Client")
def test_build_llm_runnable_config_on_adds_callbacks(
    mock_client_cls: MagicMock,
    mock_tracer_cls: MagicMock,
) -> None:
    mock_tracer_cls.return_value = MagicMock(name="tracer")
    mock_client_cls.return_value = MagicMock(name="client")

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        langsmith_tracing_enabled=True,
        langsmith_api_key="ls-secret",
        langsmith_project="vea-dev",
        langsmith_endpoint="https://api.smith.langchain.com",
    )
    cfg = build_llm_runnable_config(
        s,
        run_kind="digest",
        digest_kind="daily",
    )
    cbs = cfg.get("callbacks") or []
    assert len(cbs) == 1
    mock_client_cls.assert_called_once()
    call_kw = mock_client_cls.call_args.kwargs
    assert call_kw.get("api_key") == "ls-secret"
    assert call_kw.get("api_url") == "https://api.smith.langchain.com"
    mock_tracer_cls.assert_called_once()
    tracer_kw = mock_tracer_cls.call_args.kwargs
    assert tracer_kw.get("project_name") == "vea-dev"
    assert tracer_kw.get("client") is mock_client_cls.return_value


def test_build_llm_runnable_config_digest_includes_digest_kind_in_metadata() -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        langsmith_tracing_enabled=False,
    )
    cfg = build_llm_runnable_config(s, run_kind="digest", digest_kind="weekly")
    assert cfg.get("metadata", {}).get("digest_kind") == "weekly"


def test_build_llm_runnable_config_period_chat_omits_digest_kind() -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        langsmith_tracing_enabled=False,
    )
    cfg = build_llm_runnable_config(
        s,
        run_kind="period_chat",
        digest_kind="should_ignore",
    )
    assert "digest_kind" not in (cfg.get("metadata") or {})


def test_build_llm_tracing_enabled_without_api_key_has_no_callbacks() -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        langsmith_tracing_enabled=True,
        langsmith_api_key=None,
    )
    cfg = build_llm_runnable_config(s, run_kind="period_chat")
    assert cfg.get("callbacks") in (None, [])
