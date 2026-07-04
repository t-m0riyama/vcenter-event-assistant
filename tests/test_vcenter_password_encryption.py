"""vCenter パスワード暗号化（3-1）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import bindparam, select, text
from sqlalchemy.types import Uuid as SAUuid

from vcenter_event_assistant.db.encrypted_string import ENC_PREFIX, SecretKeyDecryptError
from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.db.session import get_engine, init_db, reset_db, session_scope
from vcenter_event_assistant.db.vcenter_password_migration import ensure_vcenter_password_storage
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.settings_binding import bind_settings


async def _raw_password(vcenter_id: uuid.UUID) -> str:
    engine = get_engine()
    stmt = text("SELECT password FROM vcenters WHERE id = :id").bindparams(
        bindparam("id", type_=SAUuid(as_uuid=True)),
    )
    async with engine.connect() as conn:
        row = (await conn.execute(stmt, {"id": vcenter_id})).first()
    assert row is not None
    return str(row[0])


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VEA_SECRET_KEY", "test-secret-key-for-encryption")
    get_settings.cache_clear()
    bind_settings(get_settings())
    yield
    get_settings.cache_clear()
    bind_settings(get_settings())


@pytest.mark.asyncio
async def test_password_stored_plaintext_when_no_secret_key() -> None:
    await reset_db()
    await init_db()
    vc_id = uuid.uuid4()
    async with session_scope() as session:
        session.add(
            VCenter(
                id=vc_id,
                name="plain-vc",
                host="vc.example",
                username="u",
                password="plain-secret",
            )
        )
    stored = await _raw_password(vc_id)
    assert stored == "plain-secret"
    assert not stored.startswith(ENC_PREFIX)
    await reset_db()


@pytest.mark.asyncio
async def test_password_encrypted_when_secret_key_set(secret_env) -> None:
    await reset_db()
    await init_db()
    vc_id = uuid.uuid4()
    async with session_scope() as session:
        session.add(
            VCenter(
                id=vc_id,
                name="enc-vc",
                host="vc.example",
                username="u",
                password="my-password",
            )
        )
    stored = await _raw_password(vc_id)
    assert stored.startswith(ENC_PREFIX)
    assert stored != "my-password"
    async with session_scope() as session:
        vc = (await session.execute(select(VCenter).where(VCenter.id == vc_id))).scalar_one()
        assert vc.password == "my-password"
    await reset_db()


@pytest.mark.asyncio
async def test_startup_migrates_legacy_plaintext_passwords(secret_env) -> None:
    await reset_db()
    await init_db()
    vc_id = uuid.uuid4()
    insert_stmt = text(
        "INSERT INTO vcenters (id, name, host, protocol, port, username, password, is_enabled, created_at) "
        "VALUES (:id, :name, :host, 'https', 443, 'u', :password, 1, CURRENT_TIMESTAMP)"
    ).bindparams(bindparam("id", type_=SAUuid(as_uuid=True)))
    async with session_scope() as session:
        await session.execute(
            insert_stmt,
            {
                "id": vc_id,
                "name": "legacy-vc",
                "host": "legacy.example",
                "password": "legacy-plain",
            },
        )
    assert await _raw_password(vc_id) == "legacy-plain"
    await ensure_vcenter_password_storage()
    stored = await _raw_password(vc_id)
    assert stored.startswith(ENC_PREFIX)
    async with session_scope() as session:
        vc = (await session.execute(select(VCenter).where(VCenter.id == vc_id))).scalar_one()
        assert vc.password == "legacy-plain"
    await reset_db()


@pytest.mark.asyncio
async def test_decrypt_fails_when_secret_key_rotated(secret_env) -> None:
    await reset_db()
    await init_db()
    vc_id = uuid.uuid4()
    async with session_scope() as session:
        session.add(
            VCenter(
                id=vc_id,
                name="rotate-vc",
                host="vc.example",
                username="u",
                password="rotate-me",
            )
        )
    get_settings.cache_clear()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("VEA_SECRET_KEY", "different-secret-key")
    get_settings.cache_clear()
    bind_settings(get_settings())
    try:
        with pytest.raises(SecretKeyDecryptError, match="Failed to decrypt"):
            async with session_scope() as session:
                vc = (await session.execute(select(VCenter).where(VCenter.id == vc_id))).scalar_one()
                assert vc.password
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        bind_settings(get_settings())
    await reset_db()


@pytest.mark.asyncio
async def test_warning_when_secret_key_missing(caplog: pytest.LogCaptureFixture) -> None:
    await reset_db()
    await init_db()
    with caplog.at_level("WARNING"):
        await ensure_vcenter_password_storage()
    assert any("VEA_SECRET_KEY is not set" in r.message for r in caplog.records)
    await reset_db()
