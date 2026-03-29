"""Pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SCHEDULER_ENABLED"] = "false"
# 開発者の .env に LLM キーがあっても、テストで外部 API を呼ばない
os.environ["LLM_API_KEY"] = ""

from vcenter_event_assistant.db.session import init_db, reset_db
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.settings import get_settings

get_settings.cache_clear()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """`test_digest*` / `test_digests_api*` を高負荷マーカーに付与（既定の addopts で除外）。

    `test_digest_llm.py` は HTTP モックのみのため `digest_heavy` に含めない。
    """
    for item in items:
        name = Path(str(item.path)).name
        if name == "test_digest_llm.py":
            continue
        if name.startswith("test_digest") or name == "test_digests_api.py":
            item.add_marker(pytest.mark.digest_heavy)


@pytest.fixture(autouse=True)
async def _db_setup() -> None:
    await reset_db()
    get_settings.cache_clear()
    await init_db()
    yield
    await reset_db()
    get_settings.cache_clear()


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
