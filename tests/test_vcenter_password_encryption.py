"""パスワード・秘密鍵の暗号化（3-1、#252）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import selectinload
from sqlalchemy.types import Uuid as SAUuid

from vcenter_event_assistant.db.encrypted_string import ENC_PREFIX, SecretKeyDecryptError
from vcenter_event_assistant.auth.directory.spec import spec_from_model
from vcenter_event_assistant.db.models import DirectoryConfig, SSHCredential, VCenter
from vcenter_event_assistant.db.session import get_engine, init_db, reset_db, session_scope
from vcenter_event_assistant.db.secret_storage_migration import ensure_secret_storage
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


async def _raw_value(table: str, column: str, row_id: uuid.UUID) -> str | None:
    stmt = text(f"SELECT {column} FROM {table} WHERE id = :id").bindparams(
        bindparam("id", type_=SAUuid(as_uuid=True)),
    )
    async with get_engine().connect() as conn:
        row = (await conn.execute(stmt, {"id": row_id})).first()
    assert row is not None
    return row[0]


async def _set_raw_value(table: str, column: str, row_id: uuid.UUID, value: str | None) -> None:
    """``EncryptedString`` を通さずに列の値を書く（鍵なしで保存された古い行の再現）。"""
    stmt = text(f"UPDATE {table} SET {column} = :value WHERE id = :id").bindparams(
        bindparam("id", type_=SAUuid(as_uuid=True)),
    )
    async with session_scope() as session:
        await session.execute(stmt, {"id": row_id, "value": value})


def _directory(name: str, bind_password: str | None) -> DirectoryConfig:
    return DirectoryConfig(
        name=name,
        kind="ldap",
        server_uris=["ldaps://ldap.example"],
        bind_dn="cn=svc,dc=example",
        bind_password=bind_password,
        user_search_base="ou=people,dc=example",
    )


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
    await ensure_secret_storage()
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
        await ensure_secret_storage()
    assert any("VEA_SECRET_KEY is not set" in r.message for r in caplog.records)
    await reset_db()


@pytest.mark.asyncio
async def test_startup_migrates_plaintext_directory_bind_password(secret_env) -> None:
    """鍵なしで保存したディレクトリの bind パスワードも、鍵を設定した起動で暗号化する（#252）。"""
    await reset_db()
    await init_db()
    async with session_scope() as session:
        directory = _directory("legacy-dir", "bind-secret")
        empty = _directory("no-password-dir", None)
        session.add_all([directory, empty])
    await _set_raw_value("directory_configs", "bind_password", directory.id, "bind-secret")
    await ensure_secret_storage()
    stored = await _raw_value("directory_configs", "bind_password", directory.id)
    assert stored is not None and stored.startswith(ENC_PREFIX)
    assert await _raw_value("directory_configs", "bind_password", empty.id) is None
    async with session_scope() as session:
        loaded = await session.scalar(
            select(DirectoryConfig)
            .where(DirectoryConfig.id == directory.id)
            .options(selectinload(DirectoryConfig.mappings))
        )
        assert loaded is not None
        # 接続に使う値は元の平文に戻る
        assert spec_from_model(loaded).bind_password == "bind-secret"
    await reset_db()


@pytest.mark.asyncio
async def test_startup_migrates_plaintext_ssh_private_key(secret_env) -> None:
    await reset_db()
    await init_db()
    async with session_scope() as session:
        credential = SSHCredential(name="legacy-ssh", private_key="PRIVATE KEY", public_key="ssh-rsa AAA")
        session.add(credential)
    await _set_raw_value("ssh_credentials", "private_key", credential.id, "PRIVATE KEY")
    await ensure_secret_storage()
    stored = await _raw_value("ssh_credentials", "private_key", credential.id)
    assert stored is not None and stored.startswith(ENC_PREFIX)
    async with session_scope() as session:
        loaded = await session.scalar(select(SSHCredential).where(SSHCredential.id == credential.id))
        assert loaded is not None and loaded.private_key == "PRIVATE KEY"
    await reset_db()


@pytest.mark.asyncio
async def test_warning_when_only_directory_secret_is_encrypted_without_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """鍵がないとき、ディレクトリにだけ暗号化済みの値があっても「鍵がない」警告を出す。"""
    await reset_db()
    await init_db()
    async with session_scope() as session:
        directory = _directory("encrypted-dir", None)
        session.add(directory)
    await _set_raw_value("directory_configs", "bind_password", directory.id, f"{ENC_PREFIX}token")
    with caplog.at_level("WARNING"):
        await ensure_secret_storage()
    assert any(
        "stored encrypted" in r.message and "directory bind password: 1" in r.message for r in caplog.records
    )
    await reset_db()
