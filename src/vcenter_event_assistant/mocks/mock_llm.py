"""モックモード用の決定論的 ChatModel（``bind_tools`` 対応）。"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

_MOCK_DIGEST_REPLY = (
    "## （モック）ダイジェスト要約\n"
    "- これは MOCK_MODE の固定応答です。外部 LLM API は呼び出していません。\n"
    "- 要注意イベントやホスト負荷の傾向を確認してください。\n"
)

_MOCK_CHAT_REPLY = (
    "（モック応答）これは MOCK_MODE の固定チャット応答です。"
    "外部 LLM には接続していません。シード／合成データを元に UI 操作を確認できます。"
)

_MOCK_SEARCH_QUERY = "vSphere host connection lost troubleshooting"


class MockChatModel(BaseChatModel):
    """固定テキストを返す。ツールが bind された初回呼び出しでは 1 回 web_search を要求する。"""

    response_text: str
    tools_bound: bool = False
    mock_search_query: str = _MOCK_SEARCH_QUERY

    @property
    def _llm_type(self) -> str:
        return "vea-mock"

    def bind_tools(self, tools: Any, **kwargs: Any) -> MockChatModel:
        """ツール定義は保持せず、フラグだけ立てた同一応答モデルを返す。"""
        _ = tools, kwargs
        return self.model_copy(update={"tools_bound": True})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        _ = stop, run_manager, kwargs
        if self.tools_bound and not any(isinstance(m, ToolMessage) for m in messages):
            msg = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": self.mock_search_query},
                        "id": "mock-web-search-1",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            msg = AIMessage(content=self.response_text)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def build_mock_chat_model(*, purpose: str = "chat") -> BaseChatModel:
    """ダイジェスト／チャット向けの固定応答モデルを返す。"""
    text = _MOCK_DIGEST_REPLY if purpose == "digest" else _MOCK_CHAT_REPLY
    return MockChatModel(response_text=text)
