"""チャット・タイムライン用の重い集計に対する上限（Issue #301）。

- ``AggregationLimitExceeded``: 集計後の行数が上限を超えたときにサービス層が投げる。HTTP への変換は呼び出し側。
- ``try_acquire`` / ``release``: 同時実行数の上限。利用者ごとと全体の 2 段で数える。

同時実行数はプロセス内のカウンタで数える。複数ワーカーで動かすと、全体の上限は「上限 × ワーカー数」になる。
空きを確かめて加算する処理は await を挟まずに行うので、イベントループの中では割り込まれない。
asyncio の基本部品を使わないため、イベントループをまたいでも使える（テストでループが替わっても壊れない）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock


class AggregationLimitExceeded(Exception):
    """集計後の行数が上限を超えた。"""

    def __init__(self, what: str, limit: int) -> None:
        super().__init__(f"{what}: aggregated rows exceed {limit}")
        self.what = what
        self.limit = limit


class AggregationBusy(Exception):
    """同時実行数の上限に達している。"""


class _ConcurrencyLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._total = 0
        self._by_owner: dict[str, int] = {}

    def try_acquire(self, owner: str, *, global_limit: int, per_owner_limit: int) -> bool:
        with self._lock:
            mine = self._by_owner.get(owner, 0)
            if self._total >= global_limit or mine >= per_owner_limit:
                return False
            self._total += 1
            self._by_owner[owner] = mine + 1
            return True

    def release(self, owner: str) -> None:
        with self._lock:
            mine = self._by_owner.get(owner, 0)
            if mine <= 1:
                self._by_owner.pop(owner, None)
            else:
                self._by_owner[owner] = mine - 1
            self._total = max(0, self._total - 1)

    def reset(self) -> None:
        with self._lock:
            self._total = 0
            self._by_owner.clear()


_limiter = _ConcurrencyLimiter()


@contextmanager
def aggregation_slot(owner: str, *, global_limit: int, per_owner_limit: int) -> Iterator[None]:
    """空きがあれば枠を 1 つ確保し、抜けるときに返す。空きがなければ待たずに ``AggregationBusy``。"""
    if not _limiter.try_acquire(owner, global_limit=global_limit, per_owner_limit=per_owner_limit):
        raise AggregationBusy(owner)
    try:
        yield
    finally:
        _limiter.release(owner)


def reset_aggregation_limiter() -> None:
    """テスト用: 数えている枠をすべて返す。"""
    _limiter.reset()
