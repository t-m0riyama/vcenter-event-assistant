"""Check authorization changes against PostgreSQL's default transaction isolation."""

import asyncio
import os
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vcenter_event_assistant.auth.service import record_local_password_failure
from vcenter_event_assistant.auth.sessions import (
    SessionPolicy,
    create_session,
    invalidate_user_authorization,
    resolve_session,
)
from vcenter_event_assistant.db.models import User
from vcenter_event_assistant.db.startup_migration import run_startup_migration
from vcenter_event_assistant.settings import Settings

POLICY = SessionPolicy(idle_timeout=timedelta(hours=1), absolute_timeout=timedelta(hours=2))


@pytest_asyncio.fixture
async def postgres_sessions():
    url = os.getenv("VEA_TEST_AUTH_POSTGRES_URL")
    if url is None:
        pytest.skip("requires a dedicated PostgreSQL test database")

    settings = Settings(_env_file=None, database_url=url)
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await run_startup_migration(engine, settings=settings)
        yield sessions, settings
    finally:
        await engine.dispose()


async def test_role_change_and_session_invalidation_are_visible_together(postgres_sessions) -> None:
    sessions, _ = postgres_sessions
    username = uuid.uuid4().hex
    async with sessions.begin() as db:
        user = User(realm_key="local", subject=username, username=username, role="viewer")
        db.add(user)
        await db.flush()
        user_id = user.id
        old_token = await create_session(db, user, POLICY)

    async with sessions.begin() as writer:
        user = await writer.get(User, user_id)
        assert user is not None
        user.role = "operator"
        await invalidate_user_authorization(writer, user)
        async with sessions() as reader:
            prior = await asyncio.wait_for(
                resolve_session(reader, old_token, POLICY, touch=False), timeout=5
            )
            assert prior is not None and prior.user.role == "viewer"

    async with sessions.begin() as db:
        assert await resolve_session(db, old_token, POLICY) is None
        user = await db.get(User, user_id)
        assert user is not None
        new_token = await create_session(db, user, POLICY)
        current = await resolve_session(db, new_token, POLICY)
        assert current is not None and current.user.role == "operator"
        assert current.session.authorization_generation == 1


async def test_account_lockout_records_concurrent_attempts(postgres_sessions) -> None:
    sessions, settings = postgres_sessions
    settings = settings.model_copy(update={"login_max_failed_attempts": 2})
    username = uuid.uuid4().hex
    async with sessions.begin() as db:
        user = User(realm_key="local", subject=username, username=username)
        db.add(user)
        await db.flush()
        user_id = user.id

    async def record_failure() -> bool:
        async with sessions.begin() as attempt_db:
            return await record_local_password_failure(attempt_db, settings, user_id, None)

    results = await asyncio.wait_for(asyncio.gather(record_failure(), record_failure()), timeout=5)
    assert sorted(results) == [False, True]
    async with sessions() as db:
        user = await db.get(User, user_id)
        assert user is not None and user.locked_until is not None
        assert user.last_login_at is None
