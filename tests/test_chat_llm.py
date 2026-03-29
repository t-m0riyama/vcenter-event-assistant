"""chat_llm.run_period_chat のモック HTTP テスト。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vcenter_event_assistant.api.schemas import ChatMessage
from vcenter_event_assistant.services.chat_llm import _CHAT_SYSTEM_PROMPT, run_period_chat
from vcenter_event_assistant.services.chat_event_time_buckets import EventTimeBucketsPayload
from vcenter_event_assistant.services.chat_period_metrics import PeriodMetricsPayload
from vcenter_event_assistant.services.digest_context import DigestContext, DigestEventTypeBucket
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


@pytest.mark.asyncio
async def test_run_period_chat_skips_http_when_no_api_key() -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key=None,
    )
    out, err, meta = await run_period_chat(
        s,
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="要約して")],
    )
    assert out == ""
    assert err is None
    assert meta is None


@pytest.mark.asyncio
async def test_run_period_chat_openai_sends_multiturn_and_returns_assistant_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-test",
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
    )
    msgs = [
        ChatMessage(role="user", content="最初の質問"),
        ChatMessage(role="assistant", content="仮の答え"),
        ChatMessage(role="user", content="追質問"),
    ]
    captured: dict[str, object] = {}

    class _StreamOk:
        status_code = 200

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self) -> object:
            yield 'data: {"choices":[{"delta":{"content":"追質問への回答"}}]}'
            yield "data: [DONE]"

    class _StreamCm:
        def __init__(self, resp: _StreamOk) -> None:
            self._resp = resp

        async def __aenter__(self) -> _StreamOk:
            return self._resp

        async def __aexit__(self, *a: object) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> _StreamCm:
            assert method == "POST"
            assert "chat/completions" in url
            body = kwargs.get("json") or {}
            captured["messages"] = body.get("messages") or []
            assert body.get("stream") is True
            return _StreamCm(_StreamOk())

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err, meta = await run_period_chat(s, context=_minimal_ctx(), messages=msgs)
    assert err is None
    assert out == "追質問への回答"
    assert meta is not None
    assert meta.json_truncated is False
    assert meta.message_turns == 3
    api_messages = captured["messages"]
    assert isinstance(api_messages, list)
    assert len(api_messages) >= 4
    assert api_messages[0] == {"role": "system", "content": _CHAT_SYSTEM_PROMPT}
    assert api_messages[1]["role"] == "user"
    assert "```json" in str(api_messages[1]["content"])
    assert api_messages[-1]["role"] == "user"
    assert api_messages[-1]["content"] == "追質問"


@pytest.mark.asyncio
async def test_run_period_chat_gemini_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="gemini-key",
        llm_provider="gemini",
        llm_model="gemini-2.0-flash",
    )

    class _FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Gemini の回答"}]}},
                ],
            }

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> _FakeResponse:
            assert "generateContent" in url
            body = kwargs.get("json") or {}
            assert "systemInstruction" in body
            assert "contents" in body
            contents = body["contents"]
            assert contents[0]["role"] == "user"
            assert "```json" in contents[0]["parts"][0]["text"]
            return _FakeResponse()

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err, meta = await run_period_chat(
        s,
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="hello")],
    )
    assert err is None
    assert out == "Gemini の回答"
    assert meta is not None
    assert meta.json_truncated is False


@pytest.mark.asyncio
async def test_run_period_chat_truncates_json_when_token_budget_tight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """集約 JSON が推定トークン上限を超えるとき、切り詰めてから API に送る。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-test",
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_chat_max_input_tokens=2500,
    )
    pad = "x" * 120_000
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    huge_ctx = DigestContext(
        from_utc=t0,
        to_utc=t0,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_event_groups=[],
        top_event_types=[
            DigestEventTypeBucket(event_type=pad, event_count=1, max_notable_score=0),
        ],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    captured: dict[str, object] = {}

    class _StreamOk:
        status_code = 200

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self) -> object:
            yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
            yield "data: [DONE]"

    class _StreamCm:
        def __init__(self, resp: _StreamOk) -> None:
            self._resp = resp

        async def __aenter__(self) -> _StreamOk:
            return self._resp

        async def __aexit__(self, *a: object) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> _StreamCm:
            body = kwargs.get("json") or {}
            captured["messages"] = body.get("messages") or []
            return _StreamCm(_StreamOk())

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err, meta = await run_period_chat(
        s,
        context=huge_ctx,
        messages=[ChatMessage(role="user", content="質問")],
    )
    assert err is None
    assert out == "ok"
    assert meta is not None
    assert meta.json_truncated is True
    api_messages = captured["messages"]
    assert isinstance(api_messages, list)
    user_block = str(api_messages[1]["content"])
    assert "…（JSON 長のため切り詰め）" in user_block
    assert len(user_block) < len(pad)


@pytest.mark.asyncio
async def test_run_period_chat_includes_period_metrics_in_user_block_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-test",
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
    )
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    pm = PeriodMetricsPayload(
        bucket_minutes=15,
        from_utc=t0,
        to_utc=t1,
        cpu=[],
    )
    captured: dict[str, object] = {}

    class _StreamOk:
        status_code = 200

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self) -> object:
            yield 'data: {"choices":[{"delta":{"content":"y"}}]}'
            yield "data: [DONE]"

    class _StreamCm:
        def __init__(self, resp: _StreamOk) -> None:
            self._resp = resp

        async def __aenter__(self) -> _StreamOk:
            return self._resp

        async def __aexit__(self, *a: object) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> _StreamCm:
            body = kwargs.get("json") or {}
            captured["messages"] = body.get("messages") or []
            return _StreamCm(_StreamOk())

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err, meta = await run_period_chat(
        s,
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="q")],
        period_metrics=pm,
    )
    assert err is None
    assert out == "y"
    assert meta is not None
    user_block = str(captured["messages"][1]["content"])
    assert "period_metrics" in user_block
    assert "digest_context" in user_block


@pytest.mark.asyncio
async def test_run_period_chat_includes_event_time_buckets_in_user_block_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-test",
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
    )
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    etb = EventTimeBucketsPayload(
        bucket_minutes=60,
        from_utc=t0,
        to_utc=t1,
        buckets=[],
    )
    captured: dict[str, object] = {}

    class _StreamOk:
        status_code = 200

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self) -> object:
            yield 'data: {"choices":[{"delta":{"content":"z"}}]}'
            yield "data: [DONE]"

    class _StreamCm:
        def __init__(self, resp: _StreamOk) -> None:
            self._resp = resp

        async def __aenter__(self) -> _StreamOk:
            return self._resp

        async def __aexit__(self, *a: object) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> _StreamCm:
            body = kwargs.get("json") or {}
            captured["messages"] = body.get("messages") or []
            return _StreamCm(_StreamOk())

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err, meta = await run_period_chat(
        s,
        context=_minimal_ctx(),
        messages=[ChatMessage(role="user", content="q")],
        event_time_buckets=etb,
    )
    assert err is None
    assert out == "z"
    assert meta is not None
    user_block = str(captured["messages"][1]["content"])
    assert "event_time_buckets" in user_block
    assert "digest_context" in user_block
