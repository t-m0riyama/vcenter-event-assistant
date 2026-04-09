"""digest_llm.augment_digest_with_llm のテスト（LangChain モック）。"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from vcenter_event_assistant.services.digest_context import DigestContext, DigestNotableEventGroup
from vcenter_event_assistant.services.digest_llm import _SYSTEM_PROMPT, augment_digest_with_llm
from vcenter_event_assistant.settings import Settings


def test_system_prompt_defines_non_overlapping_llm_section() -> None:
    """案 A: 冒頭メタ・表のなぞり再掲を禁じ、追記ブロックの役割を明示する。"""
    assert "【禁止：本文との重複】" in _SYSTEM_PROMPT
    assert "【推奨：補足として書くこと】" in _SYSTEM_PROMPT
    assert "末尾に追記される「## LLM 要約」" in _SYSTEM_PROMPT
    assert "ホスト CPU/メモリ利用率" in _SYSTEM_PROMPT


def _minimal_ctx() -> DigestContext:
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    return DigestContext(
        from_utc=t0,
        to_utc=t0,
        vcenter_count=0,
        total_events=0,
        notable_events_count=0,
        top_notable_event_groups=[],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )


@pytest.mark.asyncio
async def test_augment_skips_http_when_no_api_key() -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key=None,
    )
    md = "# t\n"
    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown=md)
    assert out == md
    assert err is None


@pytest.mark.asyncio
async def test_augment_openai_merges_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
    )
    fake = FakeListChatModel(responses=["## LLM 要約\n- テスト"])

    def _fake_build(_settings: Settings, *, purpose: object = None, config: object = None) -> FakeListChatModel:
        assert _settings is s
        _ = purpose
        _ = config
        return fake

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.build_chat_model",
        _fake_build,
    )

    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# base")
    assert err is None
    assert "## LLM 要約" in out
    assert "# base" in out


@pytest.mark.asyncio
async def test_augment_gemini_merges_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="gemini-key",
        llm_digest_provider="gemini",
        llm_digest_model="gemini-2.0-flash",
    )
    fake = FakeListChatModel(responses=["## LLM 要約\n- G"])

    def _fake_build(_settings: Settings, *, purpose: object = None, config: object = None) -> FakeListChatModel:
        assert _settings is s
        _ = purpose
        _ = config
        return fake

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.build_chat_model",
        _fake_build,
    )

    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# x")
    assert err is None
    assert "G" in out


@pytest.mark.asyncio
async def test_augment_returns_template_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-x",
        llm_digest_provider="openai_compatible",
    )

    async def _boom(*a: object, **k: object) -> tuple[str, int | None, float | None]:
        raise RuntimeError("HTTP 500: err")

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.stream_chat_to_text",
        _boom,
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
        llm_digest_api_key="sk-x",
        llm_digest_provider="openai_compatible",
    )

    async def _boom(*a: object, **k: object) -> tuple[str, int | None, float | None]:
        raise ConnectionError()

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.stream_chat_to_text",
        _boom,
    )

    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# only")
    assert out == "# only"
    assert err == "LLM 要約は省略（ConnectionError）"


@pytest.mark.asyncio
async def test_augment_timeout_shows_friendly_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """httpx.ReadTimeout は str が空になりやすい。タイムアウトである旨を日本語で示す。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-x",
        llm_digest_provider="openai_compatible",
    )

    async def _boom(*a: object, **k: object) -> tuple[str, int | None, float | None]:
        raise httpx.ReadTimeout("")

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.stream_chat_to_text",
        _boom,
    )

    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# only")
    assert out == "# only"
    assert err is not None
    assert "ReadTimeout" in (err or "")
    assert "タイムアウト" in (err or "")
    assert "LLM_DIGEST_TIMEOUT_SECONDS" in (err or "")


@pytest.mark.asyncio
async def test_augment_anonymizes_llm_input_but_keeps_template_body_in_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """匿名化オン時、LLM に渡す HumanMessage に実ホスト名が含まれず、結合後の本文はテンプレ原文を保持する。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
        llm_anonymization_enabled=True,
    )
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    host = "DIGEST-HOST-SECRET-01"
    ctx = DigestContext(
        from_utc=t0,
        to_utc=t0,
        vcenter_count=1,
        total_events=1,
        notable_events_count=0,
        top_notable_event_groups=[
            DigestNotableEventGroup(
                event_type="x",
                occurrence_count=1,
                notable_score=10,
                occurred_at_first=t0,
                occurred_at_last=t0,
                entity_name=host,
                message="m",
            )
        ],
        top_event_types=[],
        high_cpu_hosts=[],
        high_mem_hosts=[],
    )
    captured: dict[str, object] = {}

    async def _spy_stream(model: object, lc_messages: object, *, config: object = None) -> tuple[str, int | None, float | None]:
        captured["human"] = lc_messages[1].content  # type: ignore[index]
        return "## LLM 要約\n- 補足", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.build_chat_model",
        lambda _s, *, purpose=None, config=None: object(),
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.stream_chat_to_text",
        _spy_stream,
    )

    md = f"# タイトル\nホスト {host} のメモ\n"
    out, err = await augment_digest_with_llm(s, context=ctx, template_markdown=md)
    assert err is None
    assert host in out
    assert host not in str(captured.get("human"))


@pytest.mark.asyncio
async def test_augment_digest_anonymizes_extra_vcenter_in_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON に無い登録 vCenter 表示名も ``extra_vcenter_strings`` で LLM 入力から除去する。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_api_key="sk-test",
        llm_digest_provider="openai_compatible",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="gpt-4o-mini",
        llm_anonymization_enabled=True,
    )
    label = "EXTRA-VC-DISPLAY-ONLY"
    captured: dict[str, object] = {}

    async def _spy_stream(model: object, lc_messages: object, *, config: object = None) -> tuple[str, int | None, float | None]:
        captured["human"] = lc_messages[1].content  # type: ignore[index]
        return "## LLM 要約\n- ok", None, None

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.build_chat_model",
        lambda _s, *, purpose=None, config=None: object(),
    )
    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.stream_chat_to_text",
        _spy_stream,
    )

    md = f"# タイトル\n{label} について\n"
    out, err = await augment_digest_with_llm(
        s,
        context=_minimal_ctx(),
        template_markdown=md,
        extra_vcenter_strings=[label],
    )
    assert err is None
    assert label in out
    assert label not in str(captured.get("human"))
