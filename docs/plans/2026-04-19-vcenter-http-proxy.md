# vCenter HTTP Proxy サポート Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** 環境変数 `VCENTER_HTTP_PROXY`（URL 形式）で HTTP プロキシを指定し、すべての vCenter 接続をプロキシ経由にする。

**Architecture:** `settings.py` に `vcenter_http_proxy` フィールドを追加し、URL をパースしてホスト・ポートに分離する関数を `connection.py` に配置。`connect_vcenter()` にプロキシ引数を追加し、pyVmomi の `SmartConnect` に `httpProxyHost` / `httpProxyPort` を渡す。呼び出し元 4 箇所（`events.py`, `perf.py`, `vcenters.py`, `ingestion.py`）を更新する。

**Tech Stack:** Python, pyVmomi (`SmartConnect`), pydantic-settings, pytest

---

### Task 1: Settings にプロキシフィールド追加

**Files:**
- Modify: `src/vcenter_event_assistant/settings.py:19-24`
- Test: `tests/test_vcenter_proxy_settings.py`

**Step 1: テスト作成**

`tests/test_vcenter_proxy_settings.py` を新規作成:

```python
"""Tests for VCENTER_HTTP_PROXY setting."""

from __future__ import annotations

import os
from unittest.mock import patch

from vcenter_event_assistant.settings import Settings


class TestVcenterHttpProxySetting:
    """vcenter_http_proxy field parsing."""

    def test_default_is_none(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            s = Settings(database_url="sqlite+aiosqlite:///:memory:")
            assert s.vcenter_http_proxy is None

    def test_reads_from_env(self) -> None:
        with patch.dict(os.environ, {"VCENTER_HTTP_PROXY": "http://proxy.local:3128"}, clear=False):
            s = Settings(database_url="sqlite+aiosqlite:///:memory:")
            assert s.vcenter_http_proxy == "http://proxy.local:3128"

    def test_empty_string_becomes_none(self) -> None:
        with patch.dict(os.environ, {"VCENTER_HTTP_PROXY": "  "}, clear=False):
            s = Settings(database_url="sqlite+aiosqlite:///:memory:")
            assert s.vcenter_http_proxy is None
```

**Step 2: テスト実行して失敗を確認**

Run: `.venv/bin/pytest tests/test_vcenter_proxy_settings.py -v`
Expected: FAIL（`vcenter_http_proxy` フィールドが存在しない）

**Step 3: 実装**

`src/vcenter_event_assistant/settings.py` の `Settings` クラスに以下を追加（`cors_origins` フィールドの直後、`log_level` フィールドの前あたり）:

```python
    vcenter_http_proxy: str | None = Field(
        default=None,
        description=(
            "vCenter 接続用 HTTP プロキシの URL（`VCENTER_HTTP_PROXY`）。"
            "例: http://proxy.example.com:8080。未設定でプロキシなし。"
        ),
    )
```

既存の `empty_llm_optional_str_to_none` バリデータの `field_validator` に `"vcenter_http_proxy"` を追加するか、または以下の専用バリデータを追加:

```python
    @field_validator("vcenter_http_proxy", mode="before")
    @classmethod
    def empty_vcenter_proxy_to_none(cls, v: object) -> str | None:
        """空文字・空白のみは None に正規化する。"""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s or None
        return str(v).strip() or None
```

**Step 4: テスト実行して成功を確認**

Run: `.venv/bin/pytest tests/test_vcenter_proxy_settings.py -v`
Expected: 3 passed

**Step 5: コミット**

```bash
git add tests/test_vcenter_proxy_settings.py src/vcenter_event_assistant/settings.py
git commit -m "feat: add VCENTER_HTTP_PROXY setting field"
```

---

### Task 2: connection.py にプロキシ URL パース関数と connect_vcenter 拡張

**Files:**
- Modify: `src/vcenter_event_assistant/collectors/connection.py`
- Test: `tests/test_vcenter_proxy_connection.py`

**Step 1: テスト作成**

`tests/test_vcenter_proxy_connection.py` を新規作成:

```python
"""Tests for proxy support in connection.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from vcenter_event_assistant.collectors.connection import connect_vcenter, parse_proxy_url


class TestParseProxyUrl:
    """parse_proxy_url extracts host and port from a URL string."""

    def test_none_returns_none_pair(self) -> None:
        assert parse_proxy_url(None) == (None, None)

    def test_http_url_with_port(self) -> None:
        assert parse_proxy_url("http://proxy.local:3128") == ("proxy.local", 3128)

    def test_http_url_without_port_defaults_to_80(self) -> None:
        assert parse_proxy_url("http://proxy.local") == ("proxy.local", 80)

    def test_https_url_with_port(self) -> None:
        assert parse_proxy_url("https://proxy.local:8443") == ("proxy.local", 8443)


class TestConnectVcenterProxy:
    """connect_vcenter passes proxy args to SmartConnect."""

    @patch("vcenter_event_assistant.collectors.connection.SmartConnect")
    def test_no_proxy(self, mock_sc: MagicMock) -> None:
        mock_sc.return_value = MagicMock()
        connect_vcenter(host="vc", port=443, username="u", password="p")
        _, kwargs = mock_sc.call_args
        assert kwargs.get("httpProxyHost") is None

    @patch("vcenter_event_assistant.collectors.connection.SmartConnect")
    def test_with_proxy_url(self, mock_sc: MagicMock) -> None:
        mock_sc.return_value = MagicMock()
        connect_vcenter(
            host="vc", port=443, username="u", password="p",
            proxy_url="http://proxy.local:3128",
        )
        _, kwargs = mock_sc.call_args
        assert kwargs["httpProxyHost"] == "proxy.local"
        assert kwargs["httpProxyPort"] == 3128
```

**Step 2: テスト実行して失敗を確認**

Run: `.venv/bin/pytest tests/test_vcenter_proxy_connection.py -v`
Expected: FAIL（`parse_proxy_url` が存在しない）

**Step 3: 実装**

`src/vcenter_event_assistant/collectors/connection.py` を以下のように更新:

```python
"""pyVmomi connection helpers (blocking; call via asyncio.to_thread)."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

from pyVim.connect import Disconnect, SmartConnect


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    """Return object for connection test."""

    product_name: str
    product_version: str
    api_version: str
    instance_uuid: str


def parse_proxy_url(url: str | None) -> tuple[str | None, int | None]:
    """Parse a proxy URL into (host, port). Returns (None, None) if url is None or empty."""
    if not url:
        return None, None
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port
    if host and port is None:
        port = 80
    return host, port


def connect_vcenter(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    proxy_url: str | None = None,
):
    """Establish a vCenter session. Caller must Disconnect(si)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    proxy_host, proxy_port = parse_proxy_url(proxy_url)
    kwargs: dict = dict(
        host=host, user=username, pwd=password, port=port, sslContext=ctx,
    )
    if proxy_host is not None:
        kwargs["httpProxyHost"] = proxy_host
        kwargs["httpProxyPort"] = proxy_port
    return SmartConnect(**kwargs)


def disconnect(si) -> None:
    Disconnect(si)


def read_connection_info(si) -> ConnectionInfo:
    content = si.RetrieveContent()
    about = content.about
    return ConnectionInfo(
        product_name=about.name or "",
        product_version=about.version or "",
        api_version=about.apiVersion or "",
        instance_uuid=about.instanceUuid or "",
    )
```

**Step 4: テスト実行して成功を確認**

Run: `.venv/bin/pytest tests/test_vcenter_proxy_connection.py -v`
Expected: 5 passed

**Step 5: コミット**

```bash
git add tests/test_vcenter_proxy_connection.py src/vcenter_event_assistant/collectors/connection.py
git commit -m "feat: add proxy_url param to connect_vcenter with URL parser"
```

---

### Task 3: 呼び出し元の更新（events.py, perf.py）

**Files:**
- Modify: `src/vcenter_event_assistant/collectors/events.py:19-32`
- Modify: `src/vcenter_event_assistant/collectors/perf.py:62-70`

**Step 1: events.py を更新**

`fetch_events_blocking` の引数に `proxy_url: str | None = None` を追加し、`connect_vcenter` に渡す:

```python
def fetch_events_blocking(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    since: datetime | None,
    max_pages: int = 100,
    proxy_url: str | None = None,
) -> tuple[list[dict[str, Any]], datetime | None]:
    """
    Pull events from vCenter since ``since`` (inclusive window start).
    Returns normalized dicts and the max ``occurred_at`` in the batch.
    """
    si = connect_vcenter(host=host, port=port, username=username, password=password, proxy_url=proxy_url)
```

**Step 2: perf.py を更新**

`sample_hosts_blocking` の引数に `proxy_url: str | None = None` を追加し、`connect_vcenter` に渡す:

```python
def sample_hosts_blocking(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    proxy_url: str | None = None,
) -> list[dict[str, Any]]:
    """Return flattened metric sample dicts for all hosts and datastores."""
    si = connect_vcenter(host=host, port=port, username=username, password=password, proxy_url=proxy_url)
```

**Step 3: 既存テストが壊れていないことを確認**

Run: `.venv/bin/pytest tests/test_perf_sampling.py -v`
Expected: PASS（`proxy_url` はデフォルト `None` なので既存テストに影響なし）

**Step 4: コミット**

```bash
git add src/vcenter_event_assistant/collectors/events.py src/vcenter_event_assistant/collectors/perf.py
git commit -m "feat: add proxy_url param to fetch_events_blocking and sample_hosts_blocking"
```

---

### Task 4: 呼び出し元の更新（vcenters.py ルート, ingestion.py）

**Files:**
- Modify: `src/vcenter_event_assistant/api/routes/vcenters.py:89-104`
- Modify: `src/vcenter_event_assistant/services/ingestion.py:34-41,96-102`

**Step 1: vcenters.py を更新**

`test_vcenter` エンドポイント（接続テスト）でプロキシ設定を渡す:

```python
from vcenter_event_assistant.settings import get_settings

# ... 既存 import は維持 ...

@router.get("/{vcenter_id}/test")
async def test_vcenter(
    vcenter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    res = await session.execute(select(VCenter).where(VCenter.id == vcenter_id))
    vc = res.scalar_one_or_none()
    if vc is None:
        raise HTTPException(status_code=404, detail="vCenter not found")

    settings = get_settings()

    def _run():
        si = connect_vcenter(
            host=vc.host, port=vc.port, username=vc.username, password=vc.password,
            proxy_url=settings.vcenter_http_proxy,
        )
        try:
            return read_connection_info(si)
        finally:
            disconnect(si)

    try:
        info = await asyncio.to_thread(_run)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Connection failed: {exc!s}") from exc

    return {
        "ok": True,
        "product_name": info.product_name,
        "product_version": info.product_version,
        "api_version": info.api_version,
        "instance_uuid": info.instance_uuid,
    }
```

**Step 2: ingestion.py を更新**

`ingest_events_for_vcenter` と `ingest_metrics_for_vcenter` でプロキシ設定を渡す:

```python
# ingest_events_for_vcenter 内:
    settings = get_settings()
    normalized, max_ts = await asyncio.to_thread(
        fetch_events_blocking,
        host=vcenter.host,
        port=vcenter.port,
        username=vcenter.username,
        password=vcenter.password,
        since=since,
        proxy_url=settings.vcenter_http_proxy,
    )
```

```python
# ingest_metrics_for_vcenter 内:
    settings = get_settings()
    rows = await asyncio.to_thread(
        sample_hosts_blocking,
        host=vcenter.host,
        port=vcenter.port,
        username=vcenter.username,
        password=vcenter.password,
        proxy_url=settings.vcenter_http_proxy,
    )
```

注意: `ingestion.py` は既に `from vcenter_event_assistant.settings import get_settings` を import しているので追加不要。`vcenters.py` のみ import を追加する。

**Step 3: 既存テスト確認**

Run: `.venv/bin/pytest tests/test_vcenters_api.py tests/test_perf_sampling.py -v`
Expected: PASS

**Step 4: コミット**

```bash
git add src/vcenter_event_assistant/api/routes/vcenters.py src/vcenter_event_assistant/services/ingestion.py
git commit -m "feat: pass VCENTER_HTTP_PROXY to all vCenter connections"
```

---

### Task 5: .env.example にドキュメント追記

**Files:**
- Modify: `.env.example`

**Step 1: `.env.example` に追記**

`# CORS_ORIGINS=...` の行の後、`# --- Logging ---` セクションの前に以下を追加:

```
# --- vCenter HTTP Proxy（任意。未設定でプロキシなし）---
# すべての vCenter 接続（イベント取得・メトリクス収集・接続テスト）に適用。
# pyVmomi の SmartConnect (httpProxyHost / httpProxyPort) に渡される。
# VCENTER_HTTP_PROXY=http://proxy.example.com:8080
```

**Step 2: コミット**

```bash
git add .env.example
git commit -m "docs: add VCENTER_HTTP_PROXY to .env.example"
```

---

### Task 6: 全テスト実行・最終確認

**Step 1: 全テスト実行**

Run: `.venv/bin/pytest -v`
Expected: ALL PASSED

**Step 2: ruff チェック**

Run: `.venv/bin/ruff check src/vcenter_event_assistant/collectors/connection.py src/vcenter_event_assistant/settings.py tests/test_vcenter_proxy_settings.py tests/test_vcenter_proxy_connection.py`
Expected: no issues found

**Step 3: 起動確認（任意）**

Run: `.venv/bin/python -c "from vcenter_event_assistant.settings import Settings; s = Settings(database_url='sqlite+aiosqlite:///:memory:'); print('proxy:', s.vcenter_http_proxy)"`
Expected: `proxy: None`
