"""``run_blocking`` がキャンセル時にスレッドを取り残さないこと。

素の ``asyncio.to_thread`` では、タイムアウトでキャンセルされたときに待っている
コルーチンだけが解かれ、スレッドは走り続ける。pyVmomi の同期呼び出しはセッションを
掴んだままになるため、ここが分離の要になる。
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from vcenter_event_assistant_plugin_api.blocking import run_blocking


def test_returns_the_value() -> None:
    assert asyncio.run(run_blocking(lambda a, b: a + b, 1, b=2)) == 3


def test_propagates_exceptions() -> None:
    def boom() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run_blocking(boom))


async def test_cancellation_waits_for_the_blocking_call_to_return() -> None:
    started = threading.Event()
    finished = threading.Event()

    def slow() -> str:
        started.wait(5)
        # 実際の収集では、ここで pyVmomi がセッションを掴んでいる。
        finished.set()
        return "done"

    task = asyncio.create_task(run_blocking(slow))
    await asyncio.sleep(0)
    task.cancel()
    started.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    # キャンセルされても、ブロッキング処理は最後まで走り切っている。
    assert finished.is_set()


async def test_timeout_around_run_blocking_still_drains_the_thread() -> None:
    """アプリは `asyncio.timeout` で収集を打ち切る。その形をそのまま再現する。"""
    finished = threading.Event()

    def slow() -> None:
        import time

        time.sleep(0.3)
        finished.set()

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await run_blocking(slow)

    assert finished.is_set()
