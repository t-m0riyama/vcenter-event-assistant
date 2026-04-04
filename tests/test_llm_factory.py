"""llm_factory.build_chat_model の単体テスト（ネットワークなし）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vcenter_event_assistant.settings import Settings


def test_build_chat_model_rejects_copilot_cli() -> None:
    """copilot_cli は LangChain では構築しない。"""
    from vcenter_event_assistant.services import llm_factory

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="k",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="m",
        llm_digest_timeout_seconds=30.0,
        llm_chat_provider="copilot_cli",  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="copilot_cli"):
        llm_factory.build_chat_model(s, purpose="chat")


@pytest.mark.parametrize(
    ("provider", "patch_target", "model_cls_name"),
    [
        ("openai_compatible", "langchain_openai.ChatOpenAI", "ChatOpenAI"),
        ("gemini", "langchain_google_genai.ChatGoogleGenerativeAI", "ChatGoogleGenerativeAI"),
    ],
)
def test_build_chat_model_instantiates_expected_class_for_digest(
    provider: str,
    patch_target: str,
    model_cls_name: str,
) -> None:
    from vcenter_event_assistant.services import llm_factory

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="k",
        llm_digest_provider=provider,  # type: ignore[arg-type]
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="m",
        llm_digest_timeout_seconds=30.0,
    )
    with patch(patch_target) as ctor:
        mock_instance = MagicMock(name=model_cls_name)
        ctor.return_value = mock_instance
        out = llm_factory.build_chat_model(s, purpose="digest")
        assert out is mock_instance
        ctor.assert_called_once()
        call_kw = ctor.call_args.kwargs
        assert call_kw.get("model") == "m"
        if provider == "openai_compatible":
            assert call_kw.get("api_key") == "k"
            assert call_kw.get("base_url") == "https://api.openai.com/v1"
        else:
            assert call_kw.get("google_api_key") == "k"


def test_build_chat_model_chat_purpose_uses_llm_chat_model_when_set() -> None:
    from vcenter_event_assistant.services import llm_factory

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="k",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="digest-m",
        llm_digest_timeout_seconds=30.0,
        llm_chat_model="chat-m",
    )
    with patch("langchain_openai.ChatOpenAI") as ctor:
        mock_instance = MagicMock(name="ChatOpenAI")
        ctor.return_value = mock_instance
        out = llm_factory.build_chat_model(s, purpose="chat")
        assert out is mock_instance
        assert ctor.call_args.kwargs.get("model") == "chat-m"
