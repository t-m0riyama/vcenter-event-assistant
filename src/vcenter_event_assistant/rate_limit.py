"""アプリケーションレベルの簡易レート制限。"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock


class InMemoryRateLimiter:
    """プロセス内トークンバケット（単一ワーカー向け）。"""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits[key] if now - t < window_seconds]
            if len(hits) >= limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True


_rate_limiter = InMemoryRateLimiter()


def check_rate_limit(key: str, *, limit: int, window_seconds: int) -> bool:
    return _rate_limiter.allow(key, limit=limit, window_seconds=window_seconds)
