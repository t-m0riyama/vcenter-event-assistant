"""ldap3 の同期呼び出しを別スレッドで実行する（同時実行数を制限する）。"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Callable
from typing import ParamSpec, TypeVar

import anyio
import anyio.to_thread

from vcenter_event_assistant.auth.directory.connection import ConnectOptions
from vcenter_event_assistant.settings import Settings

P = ParamSpec("P")
T = TypeVar("T")

# ディレクトリへの同時接続の上限（ログインが集中してもスレッドと接続を使い切らない）
MAX_CONCURRENT_DIRECTORY_CALLS = 10

# CapacityLimiter はイベントループに束縛されるため、ループごとに用意する（テストはループが毎回変わる）
_limiters: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, anyio.CapacityLimiter] = (
    weakref.WeakKeyDictionary()
)


def _limiter() -> anyio.CapacityLimiter:
    loop = asyncio.get_running_loop()
    limiter = _limiters.get(loop)
    if limiter is None:
        limiter = _limiters[loop] = anyio.CapacityLimiter(MAX_CONCURRENT_DIRECTORY_CALLS)
    return limiter


async def run_directory_call(func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    def call() -> T:
        return func(*args, **kwargs)

    return await anyio.to_thread.run_sync(call, limiter=_limiter())


def connect_options(settings: Settings) -> ConnectOptions:
    return ConnectOptions(
        allow_insecure_tls=settings.directory_allow_insecure_tls,
        production=settings.is_production,
    )
