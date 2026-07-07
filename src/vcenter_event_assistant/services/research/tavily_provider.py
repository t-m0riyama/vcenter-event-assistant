"""Tavily Search API による ``SearchProvider`` 実装。"""

from __future__ import annotations

import httpx

from vcenter_event_assistant.services.research.search_provider import (
    SearchProvider,
    WebSearchResult,
)
from vcenter_event_assistant.settings import Settings

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilySearchProvider(SearchProvider):
    """Tavily Search API（https://tavily.com）で検索する。

    Args:
        settings: ``tavily_api_key`` 設定済みであること（``build_search_provider`` が保証）。
        transport: テスト用の ``httpx`` トランスポート差し替え。
    """

    name = "tavily"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._settings.search_timeout_seconds,
            proxy=self._settings.search_http_proxy,
            transport=self._transport,
        )

    async def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        async with self._build_client() as client:
            response = await client.post(
                _TAVILY_SEARCH_URL,
                headers={"Authorization": f"Bearer {self._settings.tavily_api_key}"},
                json={
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            response.raise_for_status()
            payload = response.json()

        results: list[WebSearchResult] = []
        for row in payload.get("results", []):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            results.append(
                WebSearchResult(
                    title=(row.get("title") or "").strip() or url,
                    url=url,
                    snippet=(row.get("content") or "").strip(),
                )
            )
        return results
