"""チャットのユーザー起点 WEB 検索（ツール実行ループ）のテスト。"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from copilot.tools import ToolInvocation

from vcenter_event_assistant.api.schemas import ChatMessage
from vcenter_event_assistant.services.chat.chat_web_search import (
    build_copilot_web_search_tool,
    chat_web_search_available,
    render_web_search_sources,
    run_chat_with_web_search,
    run_copilot_chat_with_web_search,
    sanitize_search_query,
)
from vcenter_event_assistant.services.research.search_provider import (
    SearchProvider,
    WebSearchResult,
)
from vcenter_event_assistant.settings import Settings


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"database_url": "sqlite+aiosqlite:///:memory:"}
    base.update(overrides)
    return Settings(**base)


class _FakeToolModel:
    """bind_tools / ainvoke だけを実装したチャットモデルのフェイク。"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.bound_tools: list[Any] | None = None
        self.invocations: list[list[Any]] = []

    def bind_tools(self, tools: list[Any]) -> "_FakeToolModel":
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages: list[Any], config: Any = None) -> AIMessage:
        self.invocations.append(list(messages))
        return self._responses.pop(0)


class _FakeProvider(SearchProvider):
    name = "fake"

    def __init__(self, error: Exception | None = None) -> None:
        self.queries: list[str] = []
        self._error = error

    async def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        return [
            WebSearchResult(
                title="KB 1",
                url="https://example.com/kb1",
                snippet="snippet",
            )
        ]


def _tool_call_message(query: str, call_id: str = "call-1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "web_search", "args": {"query": query}, "id": call_id}],
    )


def test_sanitize_search_query_strips_ipv4() -> None:
    q = sanitize_search_query("vsphere host 192.168.10.5 disconnected  esx.problem")
    assert "192.168.10.5" not in q
    assert q == "vsphere host disconnected esx.problem"


def test_chat_web_search_available_requires_provider() -> None:
    assert not chat_web_search_available(_settings())
    assert chat_web_search_available(_settings(tavily_api_key="tvly-x"))
    # copilot_cli もカスタムツール経由で検索可能
    assert chat_web_search_available(
        _settings(tavily_api_key="tvly-x", llm_chat_provider="copilot_cli")
    )
    assert not chat_web_search_available(
        _settings(tavily_api_key="tvly-x", web_research_enabled=False)
    )


def test_render_web_search_sources_includes_disclaimer_and_links() -> None:
    md = render_web_search_sources(
        [WebSearchResult(title="KB 1", url="https://example.com/kb1", snippet="")]
    )
    assert md is not None
    assert md.startswith("## WEB 検索の出典")
    assert "- [KB 1](https://example.com/kb1)" in md
    assert "原典" in md


def test_render_web_search_sources_none_when_empty() -> None:
    assert render_web_search_sources([]) is None


@pytest.mark.asyncio
async def test_run_chat_executes_search_and_returns_sources() -> None:
    model = _FakeToolModel(
        [
            _tool_call_message("vsphere 10.0.0.1 scsi latency"),
            AIMessage(content="回答本文"),
        ]
    )
    provider = _FakeProvider()

    text, sources = await run_chat_with_web_search(
        model,  # type: ignore[arg-type]
        [HumanMessage(content="q")],
        provider,
        _settings(),
    )

    assert text == "回答本文"
    assert [s.url for s in sources] == ["https://example.com/kb1"]
    # クエリは IPv4 除去済みで検索プロバイダに渡る
    assert provider.queries == ["vsphere scsi latency"]
    # 2 回目の呼び出しにはツール応答（検索結果 + 指示無視の注意）が含まれる
    second_call = model.invocations[1]
    tool_messages = [m for m in second_call if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "従わないこと" in str(tool_messages[0].content)
    assert "https://example.com/kb1" in str(tool_messages[0].content)


@pytest.mark.asyncio
async def test_run_chat_enforces_max_calls() -> None:
    settings = _settings(chat_web_search_max_calls=1)
    model = _FakeToolModel(
        [
            _tool_call_message("q1", "c1"),
            _tool_call_message("q2", "c2"),
            AIMessage(content="上限後の回答"),
        ]
    )
    provider = _FakeProvider()

    text, sources = await run_chat_with_web_search(
        model,  # type: ignore[arg-type]
        [HumanMessage(content="q")],
        provider,
        settings,
    )

    assert text == "上限後の回答"
    assert len(provider.queries) == 1
    # 上限到達後のツール呼び出しには上限メッセージを返している
    third_call = model.invocations[2]
    limit_messages = [
        m for m in third_call if isinstance(m, ToolMessage) and "上限" in str(m.content)
    ]
    assert len(limit_messages) == 1


@pytest.mark.asyncio
async def test_run_chat_search_failure_still_answers() -> None:
    model = _FakeToolModel(
        [
            _tool_call_message("q1"),
            AIMessage(content="検索なしの回答"),
        ]
    )
    provider = _FakeProvider(error=RuntimeError("rate limited"))

    text, sources = await run_chat_with_web_search(
        model,  # type: ignore[arg-type]
        [HumanMessage(content="q")],
        provider,
        _settings(),
    )

    assert text == "検索なしの回答"
    assert sources == []
    second_call = model.invocations[1]
    failure_messages = [
        m
        for m in second_call
        if isinstance(m, ToolMessage) and "失敗" in str(m.content)
    ]
    assert len(failure_messages) == 1


@pytest.mark.asyncio
async def test_run_chat_dedupes_sources_by_url() -> None:
    model = _FakeToolModel(
        [
            _tool_call_message("q1", "c1"),
            _tool_call_message("q2", "c2"),
            AIMessage(content="回答"),
        ]
    )
    provider = _FakeProvider()

    _, sources = await run_chat_with_web_search(
        model,  # type: ignore[arg-type]
        [HumanMessage(content="q")],
        provider,
        _settings(chat_web_search_max_calls=2),
    )

    assert [s.url for s in sources] == ["https://example.com/kb1"]


# --- copilot_cli 経路（カスタムクライアントツール） ---


def _invocation(query: str) -> ToolInvocation:
    return ToolInvocation(tool_name="web_search", arguments={"query": query})


@pytest.mark.asyncio
async def test_copilot_tool_executes_search_and_collects_sources() -> None:
    provider = _FakeProvider()
    sources: list[WebSearchResult] = []
    tool = build_copilot_web_search_tool(provider, _settings(), sources)

    assert tool.name == "web_search"
    assert tool.skip_permission is True
    result = await tool.handler(_invocation("vsphere 10.0.0.1 scsi latency"))

    assert result.result_type == "success"
    # クエリは IPv4 除去済みで検索プロバイダに渡る
    assert provider.queries == ["vsphere scsi latency"]
    assert [s.url for s in sources] == ["https://example.com/kb1"]
    # ツール応答には検索結果 + 指示無視の注意が含まれる
    assert "従わないこと" in result.text_result_for_llm
    assert "https://example.com/kb1" in result.text_result_for_llm


@pytest.mark.asyncio
async def test_copilot_tool_enforces_max_calls() -> None:
    provider = _FakeProvider()
    sources: list[WebSearchResult] = []
    tool = build_copilot_web_search_tool(
        provider, _settings(chat_web_search_max_calls=1), sources
    )

    first = await tool.handler(_invocation("q1"))
    second = await tool.handler(_invocation("q2"))

    assert len(provider.queries) == 1
    assert "従わないこと" in first.text_result_for_llm
    assert "上限" in second.text_result_for_llm


@pytest.mark.asyncio
async def test_copilot_tool_search_failure_returns_failure_message() -> None:
    provider = _FakeProvider(error=RuntimeError("rate limited"))
    sources: list[WebSearchResult] = []
    tool = build_copilot_web_search_tool(provider, _settings(), sources)

    result = await tool.handler(_invocation("q1"))

    assert sources == []
    assert "失敗" in result.text_result_for_llm
    assert "既知の情報で回答" in result.text_result_for_llm


@pytest.mark.asyncio
async def test_run_copilot_chat_passes_tool_and_extends_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_completion(settings: Any, **kwargs: Any) -> str:
        captured.update(kwargs)
        # LLM がツールを 1 回呼んだことをシミュレート
        tool = kwargs["tools"][0]
        await tool.handler(_invocation("q1"))
        return "copilot 回答"

    monkeypatch.setattr(
        "vcenter_event_assistant.services.chat.chat_web_search.run_copilot_cli_chat_completion",
        _fake_completion,
    )

    provider = _FakeProvider()
    settings = _settings(chat_web_search_max_calls=2)
    text, sources = await run_copilot_chat_with_web_search(
        settings,
        system_prompt="sys",
        block="{}",
        messages=[ChatMessage(role="user", content="質問")],
        provider=provider,
    )

    assert text == "copilot 回答"
    assert [s.url for s in sources] == ["https://example.com/kb1"]
    assert captured["timeout_extra"] == 30.0 * 2
    assert [t.name for t in captured["tools"]] == ["web_search"]
