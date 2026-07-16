"""SearchProvider 抽象と Tavily / Firecrawl 実装のテスト。"""

from __future__ import annotations

import json

import httpx
import pytest

from vcenter_event_assistant.services.research.firecrawl_provider import (
    FirecrawlSearchError,
    FirecrawlSearchProvider,
)
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


def test_build_search_provider_returns_none_for_firecrawl_without_config() -> None:
    provider = build_search_provider(_settings(search_provider="firecrawl"))
    assert provider is None


def test_build_search_provider_returns_firecrawl_with_base_url_only() -> None:
    provider = build_search_provider(
        _settings(
            search_provider="firecrawl", firecrawl_base_url="http://fc.internal:3002"
        )
    )
    assert isinstance(provider, FirecrawlSearchProvider)
    assert provider.name == "firecrawl"


def test_build_search_provider_returns_firecrawl_with_api_key_only() -> None:
    provider = build_search_provider(
        _settings(search_provider="firecrawl", firecrawl_api_key="fc-test")
    )
    assert isinstance(provider, FirecrawlSearchProvider)


def test_firecrawl_config_ignored_when_tavily_selected() -> None:
    provider = build_search_provider(_settings(firecrawl_api_key="fc-test"))
    assert provider is None


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


def _firecrawl_settings(**overrides) -> Settings:
    base = {"search_provider": "firecrawl"}
    base.update(overrides)
    return _settings(**base)


@pytest.mark.asyncio
async def test_firecrawl_search_parses_results_self_hosted_without_key() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "web": [
                        {
                            "title": "KB: SCSI latency troubleshooting",
                            "url": "https://knowledge.broadcom.com/external/article/12345",
                            "description": "Check storage path and HBA firmware.",
                        },
                        {
                            "title": "",
                            "url": "https://example.com/no-title",
                            "description": "",
                        },
                        {
                            "title": "missing url is skipped",
                            "url": "",
                            "description": "x",
                        },
                    ]
                },
            },
        )

    provider = FirecrawlSearchProvider(
        _firecrawl_settings(firecrawl_base_url="http://fc.internal:3002/"),
        transport=httpx.MockTransport(handler),
    )
    results = await provider.search("VMware vSphere event test", max_results=3)

    # 末尾スラッシュは除去され、認証ヘッダはキー未設定なら付かない
    assert captured["url"] == "http://fc.internal:3002/v2/search"
    assert captured["auth"] is None
    assert captured["body"] == {
        "query": "VMware vSphere event test",
        "limit": 3,
        "sources": ["web"],
    }
    assert len(results) == 2
    assert results[0].title == "KB: SCSI latency troubleshooting"
    assert results[0].snippet == "Check storage path and HBA firmware."
    # タイトル欠落は URL で補完、URL 欠落行はスキップ
    assert results[1].title == "https://example.com/no-title"


@pytest.mark.asyncio
async def test_firecrawl_search_uses_cloud_url_and_bearer_key() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"success": True, "data": {"web": []}})

    provider = FirecrawlSearchProvider(
        _firecrawl_settings(firecrawl_api_key="fc-test"),
        transport=httpx.MockTransport(handler),
    )
    results = await provider.search("query", max_results=1)

    assert captured["url"] == "https://api.firecrawl.dev/v2/search"
    assert captured["auth"] == "Bearer fc-test"
    assert results == []


@pytest.mark.asyncio
async def test_firecrawl_search_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    provider = FirecrawlSearchProvider(
        _firecrawl_settings(firecrawl_api_key="fc-bad"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await provider.search("query", max_results=1)


@pytest.mark.asyncio
async def test_firecrawl_search_raises_on_success_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"success": False, "error": "search backend down"}
        )

    provider = FirecrawlSearchProvider(
        _firecrawl_settings(firecrawl_base_url="http://fc.internal:3002"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FirecrawlSearchError, match="search backend down"):
        await provider.search("query", max_results=1)


@pytest.mark.asyncio
async def test_firecrawl_search_raises_on_missing_web_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": {}})

    provider = FirecrawlSearchProvider(
        _firecrawl_settings(firecrawl_base_url="http://fc.internal:3002"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FirecrawlSearchError, match="data.web"):
        await provider.search("query", max_results=1)
