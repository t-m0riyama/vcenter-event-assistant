"""LLM 失敗時のユーザー向け文言とタイムアウト判定（digest / chat 共通）。"""

from __future__ import annotations

import asyncio

import httpx


def _is_timeout_like(exc: BaseException) -> bool:
    """OpenAI SDK / httpx / asyncio いずれのタイムアウトも拾う。"""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    # SDK やプロバイダごとに例外型が異なるため、型名に "timeout" を含むものを補助的に拾う。
    # 誤検知の可能性はあるが、ユーザー向け文言はタイムアウト寄りの案内に留める。
    if "timeout" in type(exc).__name__.lower():
        return True
    try:
        from openai import APITimeoutError
    except ImportError:
        return False
    return isinstance(exc, APITimeoutError)


def _llm_failure_detail_for_user(exc: BaseException) -> str:
    """
    ユーザー向け `error_message` 用。

    - タイムアウトは `str` が空になりやすいため、日本語で「応答がタイムアウト」と明示する。
    - その他で `str(exc)` が空や空白のみのときは例外型名を返す（「省略（）」を防ぐ）。
    """
    if _is_timeout_like(exc):
        text = str(exc).strip()
        head = type(exc).__name__ + (f": {text}" if text else "")
        return (
            f"{head}（応答がタイムアウトしました。LLM_DIGEST_TIMEOUT_SECONDS または "
            "LLM_CHAT_TIMEOUT_SECONDS を延長するか、"
            "ローカル Ollama ではより軽いモデル・短いプロンプトを検討してください）"
        )
    text = str(exc).strip()
    if text:
        return text
    return type(exc).__name__
