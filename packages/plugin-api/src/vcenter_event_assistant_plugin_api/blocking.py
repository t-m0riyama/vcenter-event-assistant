"""Offloading blocking calls without losing them to cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def run_blocking(function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """ブロッキング関数をスレッドで実行する。キャンセルされても取り残さない。

    素の ``asyncio.to_thread`` との違いが重要である。``timeout_seconds`` を超えると
    アプリは収集をキャンセルするが、``to_thread`` を直接 await していると、待っている
    コルーチンだけが解かれてスレッドは走り続ける。pyVmomi の同期呼び出しはそのまま
    セッションを掴み続けるため、セッションとスレッドが取り残される。

    ここでは ``shield`` で本体を守り、キャンセル時も実際に戻るまで待ってから
    ``CancelledError`` を再送出する。
    """
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
