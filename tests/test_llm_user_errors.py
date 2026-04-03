"""llm_user_errors の振る舞いテスト（TDD）。"""

from __future__ import annotations

import httpx
import pytest


def test_llm_failure_detail_timeout_uses_japanese_hint() -> None:
    from vcenter_event_assistant.services.llm_user_errors import _llm_failure_detail_for_user

    d = _llm_failure_detail_for_user(httpx.ReadTimeout(""))
    assert "タイムアウト" in d
    assert "LLM_TIMEOUT_SECONDS" in d


def test_is_timeout_like_matches_apitimeout_if_openai_installed() -> None:
    from vcenter_event_assistant.services.llm_user_errors import _is_timeout_like

    try:
        from openai import APITimeoutError
    except ImportError:
        pytest.skip("openai not installed")
    assert _is_timeout_like(APITimeoutError("x")) is True
