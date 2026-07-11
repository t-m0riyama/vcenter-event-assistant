"""GitHub Copilot CLI（github-copilot-sdk）経由のチャット応答取得。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging

from copilot import CopilotClient
from copilot.client import SubprocessConfig
from copilot.session import PermissionRequestResult, SystemMessageAppendConfig
from copilot.tools import Tool

from vcenter_event_assistant.api.schemas import ChatMessage
from vcenter_event_assistant.services.llm.llm_profile import LlmPurpose, resolve_llm_profile

if TYPE_CHECKING:
    from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)


def format_copilot_chat_prompt(block: str, messages: list[ChatMessage]) -> str:
    """
    Copilot CLI の ``send`` は単一プロンプトのため、コンテキスト JSON と会話を 1 本の文字列に埋め込む。
    """
    parts: list[str] = [
        "以下は集約コンテキスト（JSON）とユーザー／アシスタントの会話です。\n",
        "--- コンテキスト JSON ---\n",
        block,
        "\n--- 会話 ---\n",
    ]
    for m in messages:
        role_label = "ユーザー" if m.role == "user" else "アシスタント"
        parts.append(f"{role_label}: {m.content}\n")
    parts.append("\n上記に基づき、最後のユーザーの意図に答えてください。日本語で簡潔に。")
    return "".join(parts)


def _looks_like_tool_registration_error(e: Exception) -> bool:
    """セッション生成失敗がカスタムツール登録に起因するらしいかどうか。

    モデル未対応・認証エラー等の無関係な失敗でツールなし再試行（と紛らわしい警告）を
    しないため、メッセージに tool を含む場合のみツール起因とみなす。
    """
    return "tool" in str(e).lower()


def _extract_assistant_text(ev: object | None) -> str:
    if ev is None:
        return ""
    data = getattr(ev, "data", None)
    if data is None:
        return ""
    content = getattr(data, "content", None)
    if content is None:
        return ""
    return str(content).strip()


async def _run_copilot_cli_completion_base(
    settings: Settings,
    *,
    purpose: LlmPurpose,
    system_prompt: str,
    prompt: str,
    tools: list[Tool] | None = None,
    timeout_extra: float = 0.0,
) -> str:
    prof = resolve_llm_profile(settings, purpose=purpose)
    if prof.provider != "copilot_cli":
        raise ValueError(f"_run_copilot_cli_completion_base は copilot_cli のときのみ呼び出してください（現在: {prof.provider}）")

    use_cli_session = settings.llm_copilot_cli_session_auth
    if not use_cli_session:
        token = prof.api_key.strip()
        if not token:
            raise ValueError(
                "Copilot CLI 用の認証（GitHub トークン）が空です。"
                " PAT が使えないモデルでは LLM_COPILOT_CLI_SESSION_AUTH=true と gh auth login を検討してください。"
            )

    def deny_permission(_request: object, _invocation: dict[str, str]) -> PermissionRequestResult:
        return PermissionRequestResult(
            kind="denied-by-rules",
            feedback="vcenter-event-assistant: サーバ API 経由ではツール権限を付与しません",
        )

    # PAT を渡すと一部モデル・エンドポイントで 400 になる。CLI ログインのみ使うときはトークンを渡さない。
    if use_cli_session:
        cfg = SubprocessConfig(
            github_token=None,
            cli_path=settings.llm_copilot_cli_path,
            use_logged_in_user=True,
        )
    else:
        cfg = SubprocessConfig(
            github_token=prof.api_key.strip(),
            cli_path=settings.llm_copilot_cli_path,
        )
    system_message: SystemMessageAppendConfig = {"mode": "append", "content": system_prompt}

    async with CopilotClient(cfg) as client:
        try:
            session = await client.create_session(
                on_permission_request=deny_permission,
                model=prof.model,
                streaming=False,
                # available_tools は組み込み・カスタム共通の allowlist。
                # [] だとカスタムツールも隠れるため、登録するツール名のみ許可する
                available_tools=[t.name for t in tools] if tools else [],
                tools=tools or None,
                system_message=system_message,
            )
        except Exception as e:
            if not tools or not _looks_like_tool_registration_error(e):
                raise
            # 古い CLI 等でカスタムツール登録が使えない場合は検索なしで続行する（失敗分離）
            logger.warning(
                "Copilot CLI へのカスタムツール登録に失敗したため、ツールなしで続行します: %r", e
            )
            session = await client.create_session(
                on_permission_request=deny_permission,
                model=prof.model,
                streaming=False,
                available_tools=[],
                system_message=system_message,
            )
        ev: object | None = None
        try:
            ev = await session.send_and_wait(
                prompt, timeout=prof.timeout_seconds + timeout_extra
            )
        finally:
            await session.disconnect()
        text = _extract_assistant_text(ev)
        if not text:
            raise ValueError("Copilot CLI から応答本文を取得できませんでした")
        return text


async def run_copilot_cli_chat_completion(
    settings: Settings,
    *,
    system_prompt: str,
    block: str,
    messages: list[ChatMessage],
    tools: list[Tool] | None = None,
    timeout_extra: float = 0.0,
) -> str:
    """
    Copilot CLI セッションを 1 回生成し、単一プロンプトで応答本文を返す。

    呼び出し側は ``resolve_llm_profile(..., purpose=\"chat\")`` が ``copilot_cli`` であることを保証すること。

    ``tools`` にカスタムツール（WEB 検索等）を渡すと、セッション内のツール実行を含めて
    ``send_and_wait`` で完結する。``timeout_extra`` はツール実行分のタイムアウト延長（秒）。
    """
    prompt = format_copilot_chat_prompt(block, messages)
    return await _run_copilot_cli_completion_base(
        settings,
        purpose="chat",
        system_prompt=system_prompt,
        prompt=prompt,
        tools=tools,
        timeout_extra=timeout_extra,
    )


async def run_copilot_cli_digest_completion(
    settings: Settings,
    *,
    system_prompt: str,
    user_block: str,
) -> str:
    """
    Copilot CLI セッションを 1 回生成し、単一プロンプトで応答本文を返す。ダイジェスト用。
    """
    return await _run_copilot_cli_completion_base(
        settings,
        purpose="digest",
        system_prompt=system_prompt,
        prompt=user_block,
    )
