"""llm_factory.build_chat_model の単体テスト（ネットワークなし）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vcenter_event_assistant.settings import Settings


@pytest.mark.parametrize(
    ("provider", "patch_target", "model_cls_name"),
    [
        ("openai_compatible", "langchain_openai.ChatOpenAI", "ChatOpenAI"),
        ("gemini", "langchain_google_genai.ChatGoogleGenerativeAI", "ChatGoogleGenerativeAI"),
    ],
)
def test_build_chat_model_instantiates_expected_class(
    provider: str,
    patch_target: str,
    model_cls_name: str,
) -> None:
    from vcenter_event_assistant.services import llm_factory

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="k",
        llm_provider=provider,  # type: ignore[arg-type]
        llm_base_url="https://api.openai.com/v1",
        llm_model="m",
        llm_timeout_seconds=30.0,
    )
    with patch(patch_target) as ctor:
        mock_instance = MagicMock(name=model_cls_name)
        ctor.return_value = mock_instance
        out = llm_factory.build_chat_model(s)
        assert out is mock_instance
        ctor.assert_called_once()
        call_kw = ctor.call_args.kwargs
        assert call_kw.get("model") == "m"
        if provider == "openai_compatible":
            assert call_kw.get("api_key") == "k"
            assert call_kw.get("base_url") == "https://api.openai.com/v1"
        else:
            assert call_kw.get("google_api_key") == "k"
