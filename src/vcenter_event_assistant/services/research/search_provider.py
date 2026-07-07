"""WEB 検索プロバイダの抽象インターフェース。

閉域網・API キー未設定環境では ``build_search_provider`` が ``None`` を返し、
呼び出し側は WEB 調査機能全体を静かに無効化する（例外にしない）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from vcenter_event_assistant.settings import Settings


@dataclass(frozen=True)
class WebSearchResult:
    """検索結果 1 件。``url`` は検索 API が返した実在 URL のみを想定する。"""

    title: str
    url: str
    snippet: str


class SearchProvider(ABC):
    """WEB 検索を 1 プロバイダ分実行するインターフェース。"""

    name: str = "abstract"

    @abstractmethod
    async def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        """検索を実行する。失敗した場合は例外を投げる。"""


def build_search_provider(settings: Settings) -> SearchProvider | None:
    """設定から検索プロバイダを組み立てる。利用できない構成では ``None``。

    ``None`` の条件: ``web_research_enabled=False``、または選択プロバイダの API キー未設定。
    """
    if not settings.web_research_enabled:
        return None
    if settings.search_provider == "tavily" and settings.tavily_api_key:
        from vcenter_event_assistant.services.research.tavily_provider import (
            TavilySearchProvider,
        )

        return TavilySearchProvider(settings)
    return None
