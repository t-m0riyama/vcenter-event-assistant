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

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            assert "chat/completions" in url
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "## LLM 要約\n- テスト"}}]},
            )

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

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(500, text="err")

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(),
    )

    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# only")
    assert out == "# only"
    assert err is not None
    assert "LLM 要約は省略" in (err or "")
