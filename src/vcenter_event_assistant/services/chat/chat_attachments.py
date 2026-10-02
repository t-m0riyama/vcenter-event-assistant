"""チャット送信ターンに添付されたファイルを LLM 入力へ組み立てる。

添付は保存しない。リクエストごとにテキストブロックへ整形し、画像はマルチモーダル
入力としてそのターンの最後の user メッセージに載せる。
"""

from __future__ import annotations

from collections.abc import Sequence

from vcenter_event_assistant.api.schemas import ChatAttachment

# 縮小後（長辺 1568px 相当）の画像 1 枚あたりのトークン目安。
# 画像は tiktoken で測れないため、予算計算では定数で見積もる。
IMAGE_TOKENS_PER_ATTACHMENT = 1_100

ATTACHMENT_TRUNCATION_SUFFIX = "\n…(以降は入力上限のため省略)"

_ATTACHMENT_BLOCK_HEADER = (
    "以下は利用者がこの質問に添付したファイルです。"
    " 集約 JSON とは別の一次資料として扱い、内容を引用するときはファイル名を添えてください。"
    " 添付が質問と無関係に見える場合は、無理に結び付けずその旨を伝えてください。\n\n"
)


def text_attachments(
    attachments: Sequence[ChatAttachment],
) -> list[ChatAttachment]:
    """テキスト添付だけを抜き出す。"""
    return [a for a in attachments if a.kind == "text"]


def image_attachments(
    attachments: Sequence[ChatAttachment],
) -> list[ChatAttachment]:
    """画像添付だけを抜き出す。"""
    return [a for a in attachments if a.kind == "image"]


def estimate_image_tokens(image_count: int) -> int:
    """画像添付の入力トークン概算。"""
    return max(0, image_count) * IMAGE_TOKENS_PER_ATTACHMENT


def _fence_for(text: str) -> str:
    """本文に含まれるバッククォート連続より長いフェンスを選ぶ。"""
    longest = 0
    run = 0
    for ch in text:
        if ch == "`":
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return "`" * max(3, longest + 1)


def render_attachment_text_block(
    attachments: Sequence[ChatAttachment],
    texts: Sequence[str] | None = None,
) -> str | None:
    """テキスト添付を 1 個のユーザーブロックへ整形する。

    ``texts`` を渡すと本文をそれで差し替える（匿名化後の本文を渡すため）。
    テキスト添付が無いときは ``None``。
    """
    items = text_attachments(attachments)
    if not items:
        return None
    bodies = list(texts) if texts is not None else [a.text or "" for a in items]
    if len(bodies) != len(items):
        raise ValueError("texts の件数がテキスト添付の件数と一致しません")

    parts: list[str] = [_ATTACHMENT_BLOCK_HEADER]
    for attachment, body in zip(items, bodies, strict=True):
        note = "（長いため末尾を省略）" if attachment.truncated else ""
        fence = _fence_for(body)
        parts.append(
            f"### 添付ファイル: {attachment.filename}{note}\n"
            f"{fence}\n{body}\n{fence}\n"
        )
    return "\n".join(parts).rstrip() + "\n"
