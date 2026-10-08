"""添付ブロック組み立てのテスト。"""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from vcenter_event_assistant.api.schemas import ChatAttachment
from vcenter_event_assistant.services.chat.chat_attachments import (
    IMAGE_TOKENS_PER_ATTACHMENT,
    estimate_image_tokens,
    image_attachments,
    render_attachment_text_block,
    text_attachments,
)

_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


def _text(name: str = "vmkernel.log", body: str = "line-1\nline-2") -> ChatAttachment:
    return ChatAttachment(kind="text", filename=name, media_type="text/plain", text=body)


def _image(name: str = "shot.png") -> ChatAttachment:
    return ChatAttachment(
        kind="image", filename=name, media_type="image/png", data_base64=_PNG_B64
    )


def test_render_attachment_text_block_includes_filename_and_body() -> None:
    block = render_attachment_text_block([_text(), _image()])
    assert block is not None
    assert "vmkernel.log" in block
    assert "line-1" in block
    # 画像はテキストブロックに載らない
    assert "shot.png" not in block


def test_render_attachment_text_block_returns_none_without_text_attachments() -> None:
    assert render_attachment_text_block([_image()]) is None
    assert render_attachment_text_block([]) is None


def test_render_attachment_text_block_uses_given_bodies() -> None:
    """匿名化後の本文で差し替えられる。"""
    block = render_attachment_text_block([_text(body="esxi-01")], ["__LM_ENTITY_001__"])
    assert block is not None
    assert "__LM_ENTITY_001__" in block
    assert "esxi-01" not in block


def test_render_attachment_text_block_rejects_body_count_mismatch() -> None:
    with pytest.raises(ValueError):
        render_attachment_text_block([_text(), _text("b.log")], ["only-one"])


def test_render_attachment_text_block_escapes_fence_in_body() -> None:
    """本文中のコードフェンスがブロック構造を壊さない。"""
    block = render_attachment_text_block([_text(body="```\nnested\n```")])
    assert block is not None
    assert "````" in block


def test_render_attachment_text_block_marks_truncated() -> None:
    a = ChatAttachment(
        kind="text", filename="big.log", media_type="text/plain", text="x", truncated=True
    )
    block = render_attachment_text_block([a])
    assert block is not None
    assert "省略" in block


def test_filename_is_sanitized() -> None:
    a = ChatAttachment(
        kind="text",
        filename="/tmp/we`ird\nname.log",
        media_type="text/plain",
        text="x",
    )
    assert a.filename == "weirdname.log"


def test_text_and_image_partitioning() -> None:
    items = [_text(), _image(), _text("b.csv")]
    assert [a.filename for a in text_attachments(items)] == ["vmkernel.log", "b.csv"]
    assert [a.filename for a in image_attachments(items)] == ["shot.png"]


def test_estimate_image_tokens() -> None:
    assert estimate_image_tokens(0) == 0
    assert estimate_image_tokens(3) == 3 * IMAGE_TOKENS_PER_ATTACHMENT


def test_image_attachment_data_url() -> None:
    assert _image().data_url() == f"data:image/png;base64,{_PNG_B64}"


@pytest.mark.parametrize(
    "kwargs",
    [
        # kind と中身の不一致
        {"kind": "text", "media_type": "text/plain", "data_base64": _PNG_B64},
        {"kind": "text", "media_type": "text/plain"},
        {"kind": "image", "media_type": "image/png", "text": "x"},
        {"kind": "image", "media_type": "image/png"},
        # 非対応の画像形式
        {"kind": "image", "media_type": "image/gif", "data_base64": _PNG_B64},
        # base64 として不正
        {"kind": "image", "media_type": "image/png", "data_base64": "not base64!!"},
    ],
)
def test_invalid_attachment_payloads_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        ChatAttachment(filename="f", **kwargs)


def test_oversized_image_is_rejected() -> None:
    too_big = base64.b64encode(b"0" * (10 * 1024 * 1024 + 1)).decode()
    with pytest.raises(ValidationError):
        ChatAttachment(
            kind="image", filename="big.png", media_type="image/png", data_base64=too_big
        )
