"""モックモード用 WEB 検索プロバイダ。"""

from __future__ import annotations

from vcenter_event_assistant.services.research.search_provider import (
    SearchProvider,
    WebSearchResult,
)


class MockSearchProvider(SearchProvider):
    """外部 API を呼ばず固定の検索結果を返す。"""

    name: str = "mock"

    async def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        q = (query or "").strip() or "(empty)"
        rows = [
            WebSearchResult(
                title="（モック）vSphere イベントの一般的な確認手順",
                url="https://example.com/mock/vsphere-events",
                snippet=f"クエリ「{q}」に対するデモ用スニペットです。実検索は行っていません。",
            ),
            WebSearchResult(
                title="（モック）ホスト切断時のチェックリスト",
                url="https://example.com/mock/host-disconnect",
                snippet="MOCK_MODE 用の固定結果。ネットワーク・管理エージェント・ハードウェアを確認。",
            ),
            WebSearchResult(
                title="（モック）Datastore 容量の監視ポイント",
                url="https://example.com/mock/datastore-capacity",
                snippet="使用率・スナップショット・ISO の残留などを確認するデモ文書。",
            ),
        ]
        return rows[: max(0, max_results)]
