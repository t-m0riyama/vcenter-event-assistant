"""Copilot CLI 経由チャット（github-copilot-sdk）のユニットテスト。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from vcenter_event_assistant.api.schemas import ChatMessage
from vcenter_event_assistant.services.chat_llm import run_period_chat
from vcenter_event_assistant.services.copilot_cli_llm import (
    format_copilot_chat_prompt,
    run_copilot_cli_chat_completion,
)
from vcenter_event_assistant.services.digest_context import DigestContext
from vcenter_event_assistant.settings import Settings


def _minimal_ctx() -> DigestContext:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    return DigestContext(
        from_utc=t0,
        to_utc=t0,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_event_groups=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )


def test_format_copilot_chat_prompt_includes_block_and_turns() -> None:
    block = '{"digest_context":{"total_events":1}}'
    msgs = [
        ChatMessage(role="user", content="hello"),
        ChatMessage(role="assistant", content="hi"),
        ChatMessage(role="user", content="bye"),
    ]
    out = format_copilot_chat_prompt(block, msgs)
    assert block in out
    assert "ユーザー: hello" in out
    assert "アシスタント: hi" in out
    assert "ユーザー: bye" in out


@pytest.mark.asyncio
async def test_run_copilot_cli_session_auth_omits_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI セッション認証時は SubprocessConfig に github_token を渡さない。"""
    from copilot.client import SubprocessConfig as RealSubprocessConfig

    captured: dict[str, object] = {}

    def _spy(*_a: object, **kw: object) -> object:
        captured.update(kw)
        return RealSubprocessConfig(**kw)

    monkeypatch.setattr(
        "vcenter_event_assistant.services.copilot_cli_llm.SubprocessConfig",
        _spy,
    )

    class _FakeSession:
        class _Data:
            content = "ok"

        type_name = "assistant.message"

        def __init__(self) -> None:
            self.data = _FakeSession._Data()

        async def send_and_wait(self, *_a: object, **_k: object) -> _FakeSession:
            return self

        async def disconnect(self) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def create_session(self, **_kwargs: object) -> _FakeSession:
            return _FakeSession()

    monkeypatch.setattr(
        "vcenter_event_assistant.services.copilot_cli_llm.CopilotClient",
        lambda *_a, **_k: _FakeClient(),
    )

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key=None,
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
        llm_chat_provider="copilot_cli",  # type: ignore[arg-type]
        llm_chat_model="claude-haiku-4.5",
        llm_copilot_cli_session_auth=True,
    )
    out = await run_copilot_cli_chat_completion(
        s,
        system_prompt="sys",
        block="{}",
        messages=[ChatMessage(role="user", content="hi")],
    )
    assert out == "ok"
    assert captured.get("github_token") is None
    assert captured.get("use_logged_in_user") is True


@pytest.mark.asyncio
async def test_run_copilot_cli_disconnects_when_send_and_wait_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """send_and_wait が失敗しても session.disconnect は呼ばれ、元の例外が潰れない。"""
    disconnect_mock = AsyncMock()

    class _FakeSession:
        async def send_and_wait(self, *_a: object, **_k: object) -> None:
            raise TimeoutError("copilot session idle timeout")

        async def disconnect(self) -> None:
            await disconnect_mock()

    class _FakeClient:
        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def create_session(self, **_kwargs: object) -> _FakeSession:
            return _FakeSession()

    monkeypatch.setattr(
        "vcenter_event_assistant.services.copilot_cli_llm.CopilotClient",
        lambda *_a, **_k: _FakeClient(),
    )

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="k",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
        llm_chat_provider="copilot_cli",  # type: ignore[arg-type]
        llm_chat_api_key="ghp_test",
        llm_chat_model="gpt-4.1",
    )
    with pytest.raises(TimeoutError, match="copilot session"):
        await run_copilot_cli_chat_completion(
            s,
            system_prompt="sys",
            block="{}",
            messages=[ChatMessage(role="user", content="hi")],
        )
    disconnect_mock.assert_awaited_once()


def test_settings_allows_copilot_cli_for_digest_provider() -> None:
    """ダイジェスト用 LLM に copilot_cli を指定できるようになった。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_provider="copilot_cli",
        llm_digest_api_key="ghp_test",
    )
    assert s.llm_digest_provider == "copilot_cli"


@pytest.mark.asyncio
async def test_run_period_chat_copilot_cli_calls_completion_and_returns_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-digest",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
        llm_chat_provider="copilot_cli",  # type: ignore[arg-type]
        llm_chat_api_key="ghp_chat_token",
        llm_chat_model="gpt-4.1",
    )
    async def _fake_completion(
        *args: object,
        **kwargs: object,
    ) -> str:
        assert kwargs.get("system_prompt")
        assert kwargs.get("block")
        assert kwargs.get("messages")
        return "copilot応答"

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.run_copilot_cli_chat_completion",
        _fake_completion,
        raising=True,
    )

    out, err, meta = await run_period_chat(
        s,
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="質問")],
    )
    assert err is None
    assert out == "copilot応答"
    assert meta is not None
