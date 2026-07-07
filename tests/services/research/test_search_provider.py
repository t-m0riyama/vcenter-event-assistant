"""SearchProvider 抽象と Tavily 実装のテスト。"""

from __future__ import annotations

import json

import httpx
import pytest

from vcenter_event_assistant.services.research.search_provider import (
    build_search_provider,
)
from vcenter_event_assistant.services.research.tavily_provider import (
    TavilySearchProvider,
)
from vcenter_event_assistant.settings import Settings


def _settings(**overrides) -> Settings:
    base = {"database_url": "sqlite+aiosqlite:///:memory:"}
    base.update(overrides)
    return Settings(**base)


def test_build_search_provider_returns_none_without_api_key() -> None:
    provider = build_search_provider(_settings())
    assert provider is None


def test_build_search_provider_returns_none_when_disabled() -> None:
    provider = build_search_provider(
        _settings(tavily_api_key="tvly-test", web_research_enabled=False)
    )
    assert provider is None


def test_build_search_provider_returns_tavily_with_api_key() -> None:
    provider = build_search_provider(_settings(tavily_api_key="tvly-test"))
    assert isinstance(provider, TavilySearchProvider)
    assert provider.name == "tavily"


def test_empty_api_key_normalized_to_none() -> None:
    assert build_search_provider(_settings(tavily_api_key="  ")) is None


@pytest.mark.asyncio
async def test_tavily_search_parses_results() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "KB: SCSI latency troubleshooting",
                        "url": "https://knowledge.broadcom.com/external/article/12345",
                        "content": "Check storage path and HBA firmware.",
                    },
                    {"title": "", "url": "https://example.com/no-title", "content": ""},
                    {"title": "missing url is skipped", "url": "", "content": "x"},
                ]
            },
        )

    provider = TavilySearchProvider(
        _settings(tavily_api_key="tvly-test"),
        transport=httpx.MockTransport(handler),
    )
    results = await provider.search("VMware vSphere event test", max_results=3)

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["auth"] == "Bearer tvly-test"
    assert captured["body"] == {
        "query": "VMware vSphere event test",
        "max_results": 3,
        "search_depth": "basic",
    }
    assert len(results) == 2
    assert results[0].title == "KB: SCSI latency troubleshooting"
    assert results[0].url == "https://knowledge.broadcom.com/external/article/12345"
    assert results[0].snippet == "Check storage path and HBA firmware."
    # タイトル欠落は URL で補完、URL 欠落行はスキップ
    assert results[1].title == "https://example.com/no-title"


@pytest.mark.asyncio
async def test_tavily_search_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid api key"})

    provider = TavilySearchProvider(
        _settings(tavily_api_key="tvly-bad"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await provider.search("query", max_results=1)
