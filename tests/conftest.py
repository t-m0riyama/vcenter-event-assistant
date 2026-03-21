"""Pytest fixtures."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ.pop("AUTH_BEARER_TOKEN", None)
os.environ.pop("AUTH_BASIC_USERNAME", None)
os.environ.pop("AUTH_BASIC_PASSWORD", None)

from vcenter_event_assistant.db.session import init_db, reset_db
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.settings import get_settings

get_settings.cache_clear()


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
