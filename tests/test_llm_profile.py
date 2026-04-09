"""llm_profile の単体テスト。"""

from __future__ import annotations

from vcenter_event_assistant.services.llm_profile import (
    effective_chat_api_key,
    is_chat_llm_configured,
    resolve_llm_profile,
)
from vcenter_event_assistant.settings import Settings


def _base_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_provider="openai_compatible",
        llm_digest_api_key="digest-key",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="digest-model",
        llm_digest_timeout_seconds=60.0,
    )


def test_resolve_digest_returns_digest_fields_only() -> None:
    s = _base_settings()
    p = resolve_llm_profile(s, purpose="digest")
    assert p.provider == "openai_compatible"
    assert p.api_key == "digest-key"
    assert p.base_url == "https://api.openai.com/v1"
    assert p.model == "digest-model"
    assert p.timeout_seconds == 60.0


def test_resolve_chat_falls_back_to_digest_when_chat_unset() -> None:
    s = _base_settings()
    p = resolve_llm_profile(s, purpose="chat")
    assert p.api_key == "digest-key"
    assert p.model == "digest-model"


def test_resolve_chat_overrides_when_llm_chat_fields_set() -> None:
    s = _base_settings()
    s = s.model_copy(
        update={
            "llm_chat_provider": "gemini",
            "llm_chat_api_key": "chat-key",
            "llm_chat_model": "chat-model",
        },
    )
    p = resolve_llm_profile(s, purpose="chat")
    assert p.provider == "gemini"
    assert p.api_key == "chat-key"
    assert p.model == "chat-model"
    assert p.base_url == "https://api.openai.com/v1"


def test_effective_chat_api_key_prefers_chat_key() -> None:
    s = _base_settings()
    s = s.model_copy(update={"llm_chat_api_key": "only-chat"})
    assert effective_chat_api_key(s) == "only-chat"


def test_effective_chat_api_key_falls_back_to_digest_key() -> None:
    s = _base_settings()
    assert effective_chat_api_key(s) == "digest-key"


def test_effective_chat_api_key_empty_when_both_empty() -> None:
    s = _base_settings()
    s = s.model_copy(update={"llm_digest_api_key": None, "llm_chat_api_key": None})
    assert effective_chat_api_key(s) == ""


def test_is_chat_llm_configured_copilot_session_without_keys() -> None:
    """copilot_cli + CLI セッション認証なら API キーなしでもチャット可能。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_provider="openai_compatible",
        llm_digest_api_key=None,
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="m",
        llm_digest_timeout_seconds=60.0,
        llm_chat_provider="copilot_cli",  # type: ignore[arg-type]
        llm_chat_model="claude-haiku-4.5",
        llm_copilot_cli_session_auth=True,
    )
    assert is_chat_llm_configured(s) is True


def test_is_chat_llm_configured_false_when_copilot_without_session_and_no_keys() -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_provider="openai_compatible",
        llm_digest_api_key=None,
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="m",
        llm_digest_timeout_seconds=60.0,
        llm_chat_provider="copilot_cli",  # type: ignore[arg-type]
        llm_chat_model="x",
        llm_copilot_cli_session_auth=False,
    )
    assert is_chat_llm_configured(s) is False
