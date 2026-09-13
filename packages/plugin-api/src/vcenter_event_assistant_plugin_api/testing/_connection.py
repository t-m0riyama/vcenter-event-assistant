"""``CollectionContext.open_vcenter_connection`` のテスト用実装。

アプリは接続を開いて ``si`` を渡し、収集の後で必ず閉じる。ここではその形だけを
再現し、**開いた回数と閉じた回数が一致するか**を記録する。接続を開いたまま例外で
抜ける実装は、本番では vCenter のセッションを溜め続けるが手元では気づけない。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from vcenter_event_assistant_plugin_api import ConnectionFactory

__all__ = [
    "ConnectionLeakError",
    "ConnectionLog",
    "fake_connection",
    "failing_connection",
    "recording_connection",
]


class ConnectionLeakError(AssertionError):
    """接続の開閉が釣り合っていない。"""


class ConnectionLog:
    """接続の open / close の記録。"""

    def __init__(self) -> None:
        self.enters = 0
        self.exits = 0

    @property
    def leaked(self) -> int:
        """開いたまま閉じられていない数。"""
        return self.enters - self.exits

    def assert_balanced(self, *, expected: int | None = None) -> None:
        """開閉が釣り合っていることを確認する。

        Args:
            expected: 期待する open の回数。``None`` なら回数は問わない。
        """
        if self.leaked:
            raise ConnectionLeakError(
                f"{self.leaked} vCenter connection(s) were left open "
                f"(opened {self.enters}, closed {self.exits}); "
                "open it with `async with context.open_vcenter_connection() as si:`"
            )
        if expected is not None and self.enters != expected:
            raise AssertionError(
                f"expected {expected} vCenter connection(s), got {self.enters}"
            )

    def __repr__(self) -> str:
        return f"ConnectionLog(enters={self.enters}, exits={self.exits})"


def fake_connection(service_instance: Any) -> ConnectionFactory:
    """``si`` として ``service_instance`` を渡す接続ファクトリを作る。"""
    factory, _log = recording_connection(service_instance)
    return factory


def recording_connection(
    service_instance: Any,
) -> tuple[ConnectionFactory, ConnectionLog]:
    """接続ファクトリと、その開閉を記録する :class:`ConnectionLog` を返す。"""
    log = ConnectionLog()

    @asynccontextmanager
    async def factory() -> AsyncIterator[Any]:
        log.enters += 1
        try:
            yield service_instance
        finally:
            log.exits += 1

    return factory, log


def failing_connection(error: BaseException) -> ConnectionFactory:
    """接続の確立に失敗するファクトリを作る。

    ``mock_mode=True`` のとき接続を開かないことを確かめるのにも使える
    （開いてしまえばこの例外で落ちる）。
    """

    @asynccontextmanager
    async def factory() -> AsyncIterator[Any]:
        raise error
        yield  # pragma: no cover - 到達しない（ジェネレータであるために必要）

    return factory
