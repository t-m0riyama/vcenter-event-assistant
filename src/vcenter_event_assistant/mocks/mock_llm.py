"""モックモード用の決定論的 ChatModel。"""

from __future__ import annotations

from itertools import cycle

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

_MOCK_DIGEST_REPLY = (
    "## （モック）ダイジェスト要約\n"
    "- これは MOCK_MODE の固定応答です。外部 LLM API は呼び出していません。\n"
    "- 要注意イベントやホスト負荷の傾向を確認してください。\n"
)

_MOCK_CHAT_REPLY = (
    "（モック応答）これは MOCK_MODE の固定チャット応答です。"
    "外部 LLM には接続していません。シード／合成データを元に UI 操作を確認できます。"
)


def build_mock_chat_model(*, purpose: str = "chat") -> BaseChatModel:
    """ダイジェスト／チャット向けの無限サイクル固定応答モデルを返す。"""
    text = _MOCK_DIGEST_REPLY if purpose == "digest" else _MOCK_CHAT_REPLY
    return GenericFakeChatModel(messages=cycle([AIMessage(content=text)]))
