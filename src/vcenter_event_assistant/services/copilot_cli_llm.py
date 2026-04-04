"""GitHub Copilot CLI（github-copilot-sdk）経由のチャット応答取得。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from copilot import CopilotClient
from copilot.client import SubprocessConfig
from copilot.session import PermissionRequestResult, SystemMessageAppendConfig

from vcenter_event_assistant.api.schemas import ChatMessage
from vcenter_event_assistant.services.llm_profile import resolve_llm_profile

if TYPE_CHECKING:
    from vcenter_event_assistant.settings import Settings


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


async def run_copilot_cli_chat_completion(
    settings: Settings,
    *,
    system_prompt: str,
    block: str,
    messages: list[ChatMessage],
) -> str:
    """
    Copilot CLI セッションを 1 回生成し、単一プロンプトで応答本文を返す。

    呼び出し側は ``resolve_llm_profile(..., purpose=\"chat\")`` が ``copilot_cli`` であることを保証すること。
    """
    prof = resolve_llm_profile(settings, purpose="chat")
    if prof.provider != "copilot_cli":
        raise ValueError("run_copilot_cli_chat_completion は copilot_cli のときのみ呼び出してください")
    token = prof.api_key.strip()
    if not token:
        raise ValueError("Copilot CLI 用の認証（GitHub トークン）が空です")

    def deny_permission(_request: object, _invocation: dict[str, str]) -> PermissionRequestResult:
        return PermissionRequestResult(
            kind="denied-by-rules",
            feedback="vcenter-event-assistant: サーバ API 経由ではツール権限を付与しません",
        )

    cfg = SubprocessConfig(
        github_token=token,
        cli_path=settings.llm_copilot_cli_path,
    )
    prompt = format_copilot_chat_prompt(block, messages)
    system_message: SystemMessageAppendConfig = {"mode": "append", "content": system_prompt}

    async with CopilotClient(cfg) as client:
        session = await client.create_session(
            on_permission_request=deny_permission,
            model=prof.model,
            streaming=False,
            available_tools=[],
            system_message=system_message,
        )
        ev: object | None = None
        try:
            ev = await session.send_and_wait(prompt, timeout=prof.timeout_seconds)
        finally:
            await session.disconnect()
        text = _extract_assistant_text(ev)
        if not text:
            raise ValueError("Copilot CLI から応答本文を取得できませんでした")
        return text
