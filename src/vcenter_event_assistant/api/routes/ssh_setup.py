"""用途ごとに分離した SSH の鍵と接続先の設定 API。"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.auth_deps import Principal, get_current_principal
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.diagnostics_audit import commit_audit
from vcenter_event_assistant.api.routes.setup_common import SafeSetupRoute
from vcenter_event_assistant.db.models import SSHConnection, SSHCredential
from vcenter_event_assistant.services.ssh_management import (
    SSHPurpose,
    check_ssh_port,
    connection_read,
    fingerprint,
    read_ssh_connection,
)
from vcenter_event_assistant.services.vcenter_host_validation import (
    validate_vcenter_host,
)
from vcenter_event_assistant.settings import Settings
from vcenter_event_assistant_plugin_api.network import (
    check_ssh_address,
    resolve_ssh_address,
)


class KeyInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    private_key: SecretStr | None = None


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    host: str = Field(min_length=1, max_length=512)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=512)
    credential_id: UUID


class ApprovalInput(BaseModel):
    fingerprint: str
    revision: int


def validate_host(host: str, settings: Settings) -> str:
    # 管理者が登録する接続先にはプライベート IP を許可し、ループバック等は拒否する。
    # ホスト名は接続直前の名前解決でも確かめる。
    normalized = host.strip()
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        try:
            return validate_vcenter_host(
                normalized,
                resolve_dns=False,
                allowed_suffixes=settings.vcenter_allowed_host_suffix_list or None,
            )
        except ValueError:
            raise HTTPException(
                422, "ホスト名またはIPアドレスを確認してください。"
            ) from None
    try:
        check_ssh_address(str(address))
    except ValueError:
        raise HTTPException(422, "このIPアドレスにはSSH接続できません。") from None
    return str(address)


def validate_port(port: int, settings: Settings) -> None:
    try:
        check_ssh_port(settings, port)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def ssh_setup_router(
    purpose: SSHPurpose,
    *,
    route_class: type[SafeSetupRoute],
    mutation_dependencies=(),
    ensure_not_active: Callable[[AsyncSession, UUID], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter(route_class=route_class)

    async def connection_result(session, request, principal, row, event):
        result = connection_read(row)
        if purpose == "diagnostics":
            await commit_audit(
                session,
                request,
                principal,
                f"ssh.connection.{event}",
                connection_id=row.id,
                name=row.name,
                host=row.host,
                port=row.port,
                ssh_username=row.username,
                credential_id=row.credential_id,
            )
        return result

    async def change_connection(session, request, principal, row, event, **changes):
        # ホスト鍵の取得中などに接続先が変更された場合は書き込みを断る。
        updated = await session.scalar(
            update(SSHConnection)
            .where(
                SSHConnection.id == row.id,
                SSHConnection.purpose == purpose,
                SSHConnection.revision == row.revision,
            )
            .values(**changes, revision=row.revision + 1)
            .returning(SSHConnection)
            .execution_options(populate_existing=True)
        )
        if updated is None:
            raise HTTPException(
                409, "接続先が変更されました。最新の設定を読み直してください。"
            )
        return await connection_result(session, request, principal, updated, event)

    @router.get("/ssh/credentials")
    async def list_credentials(session: AsyncSession = Depends(get_session)):
        # 一覧では公開情報だけを読み、秘密鍵は復号しない。
        rows = (
            await session.execute(
                select(
                    SSHCredential.id, SSHCredential.name, SSHCredential.public_key
                ).where(SSHCredential.purpose == purpose)
            )
        ).all()
        return [
            {"id": str(i), "name": name, "public_key": pub} for i, name, pub in rows
        ]

    @router.post("/ssh/credentials", dependencies=mutation_dependencies)
    async def create_credential(
        body: KeyInput,
        request: Request,
        principal: Principal = Depends(get_current_principal),
        session: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_app_settings),
    ):
        import asyncssh

        if not settings.vea_secret_key:
            raise HTTPException(422, "管理者にVEA_SECRET_KEYの設定を依頼してください。")
        try:
            if body.private_key is None:
                key = await asyncio.to_thread(
                    asyncssh.generate_private_key, "ssh-rsa", key_size=3072
                )
            else:
                value = body.private_key.get_secret_value()
                if len(value.encode()) > 32768:
                    raise ValueError()
                key = asyncssh.import_private_key(value)
            private = key.export_private_key("openssh").decode()
            public = key.export_public_key("openssh").decode()
        except Exception:
            raise HTTPException(
                422,
                "秘密鍵を読み込めません。パスフレーズ不要のSSH秘密鍵を選んでください。",
            ) from None
        row = SSHCredential(
            name=body.name, private_key=private, public_key=public, purpose=purpose
        )
        session.add(row)
        await session.flush()
        result = {"id": str(row.id), "name": row.name, "public_key": row.public_key}
        if purpose == "diagnostics":
            await commit_audit(
                session,
                request,
                principal,
                "ssh.credential.created",
                credential_id=row.id,
                name=row.name,
            )
        return result

    @router.get("/ssh/credentials/{identifier}/public-key")
    async def public_key(
        identifier: UUID, session: AsyncSession = Depends(get_session)
    ):
        row = await session.execute(
            select(SSHCredential.public_key).where(
                SSHCredential.id == identifier, SSHCredential.purpose == purpose
            )
        )
        value = row.scalar_one_or_none()
        if value is None:
            raise HTTPException(404, "SSH鍵が見つかりません。")
        return {"public_key": value}

    @router.delete("/ssh/credentials/{identifier}", dependencies=mutation_dependencies)
    async def delete_credential(
        identifier: UUID,
        request: Request,
        principal: Principal = Depends(get_current_principal),
        session: AsyncSession = Depends(get_session),
    ):
        name = await session.scalar(
            select(SSHCredential.name).where(
                SSHCredential.id == identifier, SSHCredential.purpose == purpose
            )
        )
        if name is None:
            raise HTTPException(404, "SSH鍵が見つかりません。")
        if await session.scalar(
            select(SSHConnection.id)
            .where(SSHConnection.credential_id == identifier)
            .limit(1)
        ):
            raise HTTPException(409, "接続先で使用中の鍵は削除できません。")
        try:
            deleted = await session.scalar(
                delete(SSHCredential)
                .where(SSHCredential.id == identifier, SSHCredential.purpose == purpose)
                .returning(SSHCredential.id)
            )
        except IntegrityError:
            # 接続先の作成と削除が競合したときも外部キーで保護する。
            raise HTTPException(409, "接続先で使用中の鍵は削除できません。") from None
        if deleted is None:
            raise HTTPException(404, "SSH鍵が見つかりません。")
        if purpose == "diagnostics":
            await commit_audit(
                session,
                request,
                principal,
                "ssh.credential.deleted",
                credential_id=identifier,
                name=name,
            )
        return {"ok": True}

    @router.get("/ssh/connections")
    async def list_connections(session: AsyncSession = Depends(get_session)):
        return [
            connection_read(row)
            for row in (
                await session.scalars(
                    select(SSHConnection).where(SSHConnection.purpose == purpose)
                )
            ).all()
        ]

    @router.post("/ssh/connections", dependencies=mutation_dependencies)
    async def create_connection(
        body: ConnectionInput,
        request: Request,
        principal: Principal = Depends(get_current_principal),
        session: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_app_settings),
    ):
        if not await session.scalar(
            select(SSHCredential.id).where(
                SSHCredential.id == body.credential_id, SSHCredential.purpose == purpose
            )
        ):
            raise HTTPException(422, "SSH鍵を選択してください。")
        validate_port(body.port, settings)
        row = SSHConnection(
            **body.model_dump(exclude={"host"}),
            host=validate_host(body.host, settings),
            revision=1,
            purpose=purpose,
        )
        session.add(row)
        try:
            await session.flush()
        except IntegrityError:
            raise HTTPException(422, "SSH鍵を選択してください。") from None
        return await connection_result(session, request, principal, row, "created")

    async def get_connection(session, identifier):
        row = await read_ssh_connection(session, identifier, purpose)
        if not row:
            raise HTTPException(404, "接続先が見つかりません。")
        return row

    @router.put("/ssh/connections/{identifier}", dependencies=mutation_dependencies)
    async def update_connection(
        identifier: UUID,
        body: ConnectionInput,
        request: Request,
        principal: Principal = Depends(get_current_principal),
        session: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_app_settings),
    ):
        row = await get_connection(session, identifier)
        if ensure_not_active is not None:
            await ensure_not_active(session, identifier)
        if not await session.scalar(
            select(SSHCredential.id).where(
                SSHCredential.id == body.credential_id, SSHCredential.purpose == purpose
            )
        ):
            raise HTTPException(422, "SSH鍵が見つかりません。")
        host = validate_host(body.host, settings)
        validate_port(body.port, settings)
        changes = body.model_dump()
        changes["host"] = host
        if (row.host, row.port) != (host, body.port):
            changes.update(candidate_key=None, approved_key=None)
        try:
            return await change_connection(
                session, request, principal, row, "updated", **changes
            )
        except IntegrityError:
            raise HTTPException(422, "SSH鍵が見つかりません。") from None

    @router.post(
        "/ssh/connections/{identifier}/host-key", dependencies=mutation_dependencies
    )
    async def probe_host_key(
        identifier: UUID,
        request: Request,
        principal: Principal = Depends(get_current_principal),
        session: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_app_settings),
    ):
        import asyncssh

        row = await get_connection(session, identifier)
        validate_port(row.port, settings)
        # 名前のまま接続すると、もう一度名前解決が起き、検証していない IP（ループバックや
        # メタデータ）に接続し得る（DNS rebinding、監査 M-3）。解決して検証した IP に接続する。
        try:
            async with asyncio.timeout(10):
                address = await resolve_ssh_address(row.host, row.port)
        except (ValueError, TimeoutError):
            raise HTTPException(
                422,
                "この接続先には接続できません。ホスト名の名前解決の結果を確認してください。",
            ) from None
        try:
            async with asyncio.timeout(10):
                key = await asyncssh.get_server_host_key(address, row.port, config=None)
            if key is None:
                raise ValueError()
        except Exception:
            raise HTTPException(
                422,
                "ホスト鍵を取得できません。SSHの有効化・接続先・ポートを確認してください。",
            ) from None
        return await change_connection(
            session,
            request,
            principal,
            row,
            "host_key_probed",
            candidate_key=key.export_public_key("openssh").decode(),
        )

    @router.post(
        "/ssh/connections/{identifier}/approve", dependencies=mutation_dependencies
    )
    async def approve_host_key(
        identifier: UUID,
        body: ApprovalInput,
        request: Request,
        principal: Principal = Depends(get_current_principal),
        session: AsyncSession = Depends(get_session),
    ):
        row = await get_connection(session, identifier)
        if (
            row.revision != body.revision
            or not row.candidate_key
            or fingerprint(row.candidate_key) != body.fingerprint
        ):
            raise HTTPException(409, "ホスト鍵の取得をやり直してください。")
        if ensure_not_active is not None and row.approved_key != row.candidate_key:
            await ensure_not_active(session, identifier)
        return await change_connection(
            session,
            request,
            principal,
            row,
            "host_key_approved",
            approved_key=row.candidate_key,
        )

    return router
