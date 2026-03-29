"""digest_llm.augment_digest_with_llm のモック HTTP テスト。"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from vcenter_event_assistant.services.digest_context import DigestContext
from vcenter_event_assistant.services.digest_llm import augment_digest_with_llm
from vcenter_event_assistant.settings import Settings


def _minimal_ctx() -> DigestContext:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    return DigestContext(
        from_utc=t0,
        to_utc=t0,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_events=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )


@pytest.mark.asyncio
async def test_augment_skips_http_when_no_api_key() -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key=None,
    )
    md = "# t\n"
    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown=md)
    assert out == md
    assert err is None


@pytest.mark.asyncio
async def test_augment_openai_merges_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-test",
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
    )

    class _StreamOk:
        status_code = 200

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self) -> object:
            yield 'data: {"choices":[{"delta":{"content":"## LLM 要約\\n- テスト"}}]}'
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
            assert "chat/completions" in url
            body = kwargs.get("json") or {}
            assert body.get("stream") is True
            return _StreamCm(_StreamOk())

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# base")
    assert err is None
    assert "## LLM 要約" in out
    assert "# base" in out


@pytest.mark.asyncio
async def test_augment_gemini_merges_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="gemini-key",
        llm_provider="gemini",
        llm_model="gemini-2.0-flash",
    )

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            assert "generativelanguage.googleapis.com" in url
            assert "generateContent" in url
            assert "?key=" not in url
            hdrs = kwargs.get("headers") or {}
            assert hdrs.get("x-goog-api-key") == "gemini-key"
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {"content": {"parts": [{"text": "## LLM 要約\n- G"}]}}
                    ]
                },
            )

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# x")
    assert err is None
    assert "G" in out


@pytest.mark.asyncio
async def test_augment_returns_template_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-x",
        llm_provider="openai_compatible",
    )

    class _StreamErr:
        status_code = 500

        async def aread(self) -> bytes:
            return b"err"

        async def aiter_lines(self) -> object:
            if False:
                yield

    class _StreamCm:
        async def __aenter__(self) -> _StreamErr:
            return _StreamErr()

        async def __aexit__(self, *a: object) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> _StreamCm:
            return _StreamCm()

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# only")
    assert out == "# only"
    assert err is not None
    assert "LLM 要約は省略" in (err or "")
    assert "HTTP 500" in (err or "")


@pytest.mark.asyncio
async def test_augment_uses_exception_type_when_str_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """str(e) が空のときは括弧内に例外型名を入れる（「LLM 要約は省略（）」を防ぐ）。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-x",
        llm_provider="openai_compatible",
    )

    class _StreamCm:
        async def __aenter__(self) -> None:
            raise ConnectionError()

        async def __aexit__(self, *a: object) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> _StreamCm:
            return _StreamCm()

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# only")
    assert out == "# only"
    assert err == "LLM 要約は省略（ConnectionError）"


@pytest.mark.asyncio
async def test_augment_timeout_shows_friendly_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """httpx.ReadTimeout は str が空になりやすい。タイムアウトである旨を日本語で示す。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-x",
        llm_provider="openai_compatible",
    )

    class _StreamTimeout:
        status_code = 200

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self) -> object:
            raise httpx.ReadTimeout("")
            if False:
                yield ""

    class _StreamCm:
        async def __aenter__(self) -> _StreamTimeout:
            return _StreamTimeout()

        async def __aexit__(self, *a: object) -> None:
            return None

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> _StreamCm:
            return _StreamCm()

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# only")
    assert out == "# only"
    assert err is not None
    assert "ReadTimeout" in (err or "")
    assert "タイムアウト" in (err or "")
    assert "LLM_TIMEOUT_SECONDS" in (err or "")
