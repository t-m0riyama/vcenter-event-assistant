"""Firecrawl Search API (v2) による ``SearchProvider`` 実装。

クラウド（https://firecrawl.dev）とセルフホストの両方に対応する。
セルフホストの ``/search`` は Firecrawl 単体では動かず、裏に検索バックエンド
（SearXNG または Serper 等）の構成が必要な点に注意。
"""

from __future__ import annotations

import httpx

from vcenter_event_assistant.services.research.search_provider import (
    SearchProvider,
    WebSearchResult,
)
from vcenter_event_assistant.settings import Settings

_FIRECRAWL_CLOUD_BASE_URL = "https://api.firecrawl.dev"


class FirecrawlSearchError(RuntimeError):
    """Firecrawl が HTTP 200 でも検索失敗を返した場合の例外。"""


class FirecrawlSearchProvider(SearchProvider):
    """Firecrawl Search API v2（``POST {base_url}/v2/search``）で検索する。

    Args:
        settings: ``firecrawl_base_url`` または ``firecrawl_api_key`` 設定済みで
            あること（``build_search_provider`` が保証）。
        transport: テスト用の ``httpx`` トランスポート差し替え。
    """

    name = "firecrawl"

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

    def _search_url(self) -> str:
        base = self._settings.firecrawl_base_url or _FIRECRAWL_CLOUD_BASE_URL
        return f"{base.rstrip('/')}/v2/search"

    def _headers(self) -> dict[str, str]:
        # セルフホストは認証なし構成が普通なのでキーは任意
        if self._settings.firecrawl_api_key:
            return {"Authorization": f"Bearer {self._settings.firecrawl_api_key}"}
        return {}

    async def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        async with self._build_client() as client:
            response = await client.post(
                self._search_url(),
                headers=self._headers(),
                json={
                    "query": query,
                    "limit": max_results,
                    "sources": ["web"],
                },
            )
            response.raise_for_status()
            payload = response.json()

        if payload.get("success") is not True:
            raise FirecrawlSearchError(
                f"Firecrawl search failed: {payload.get('error') or payload}"
            )
        web_rows = (payload.get("data") or {}).get("web")
        if not isinstance(web_rows, list):
            raise FirecrawlSearchError("Firecrawl search response missing data.web")

        results: list[WebSearchResult] = []
        for row in web_rows:
            url = (row.get("url") or "").strip()
            if not url:
                continue
            results.append(
                WebSearchResult(
                    title=(row.get("title") or "").strip() or url,
                    url=url,
                    snippet=(row.get("description") or "").strip(),
                )
            )
        return results
