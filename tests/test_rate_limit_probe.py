"""外へ接続して確かめる API の rate limit（監査 M-3、Issue #237）。

ホスト鍵の取得などを繰り返し呼ぶと、応答時間の差からポートスキャンができる。
パスに ID が入るので、完全一致ではなくパターンで照合する。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from vcenter_event_assistant.main import _rate_limit_spec, create_app
from vcenter_event_assistant.rate_limit import _rate_limiter
from vcenter_event_assistant.settings import get_settings

XHR = {"X-Requested-With": "XMLHttpRequest"}
ID = "0b8e7c1e-6a43-4f3e-9d3c-2f6f1d0c9a11"


@pytest.mark.parametrize(
    ("method", "path", "bucket"),
    [
        ("POST", f"/api/plugins/ssh/connections/{ID}/host-key", "probe"),
        ("POST", "/api/plugins/collectors/vea.remote.logs/draft/actions/test", "probe"),
        ("GET", f"/api/plugins/vcenters/{ID}/hosts", "probe"),
        ("GET", f"/api/vcenters/{ID}/test", "probe"),
        ("POST", "/api/auth/login", "login"),
        ("POST", "/api/plugins/installed/upload", "plugins"),
    ],
)
def test_matches_probe_paths_by_pattern(method: str, path: str, bucket: str) -> None:
    spec = _rate_limit_spec(method, path)
    assert spec is not None and spec[0] == bucket


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"/api/plugins/ssh/connections/{ID}/host-key"),
        ("POST", "/api/plugins/ssh/connections"),
        ("POST", f"/api/plugins/ssh/connections/{ID}/approve"),
        ("POST", f"/api/plugins/ssh/connections/{ID}/extra/host-key"),
        ("GET", f"/api/vcenters/{ID}"),
        ("GET", "/api/auth/login"),
        ("POST", "/api/auth/login/extra"),
    ],
)
def test_does_not_limit_other_paths_or_methods(method: str, path: str) -> None:
    assert _rate_limit_spec(method, path) is None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"/api/plugins/ssh/connections/{ID}/host-key"),
        ("GET", f"/api/vcenters/{ID}/test"),
    ],
)
async def test_probe_paths_return_429_over_the_limit(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    monkeypatch.delenv("VEA_PYTEST")
    monkeypatch.setenv("RATE_LIMIT_PROBE_PER_MINUTE", "2")
    get_settings.cache_clear()
    _rate_limiter._hits.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as ac:
            codes = [(await ac.request(method, path, headers=XHR)).status_code for _ in range(3)]
    finally:
        _rate_limiter._hits.clear()
        get_settings.cache_clear()
    assert codes[:2] != [429, 429]
    assert codes[2] == 429
