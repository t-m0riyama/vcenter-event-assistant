"""vCenter CRUD and connection test."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.schemas import VCenterCreate, VCenterRead, VCenterUpdate
from vcenter_event_assistant.collectors.connection import (
    connect_vcenter,
    disconnect,
    format_connection_error_detail,
    read_connection_info,
)
from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.security_startup import passwords_may_be_stored
from vcenter_event_assistant.services.vcenter_host_validation import validate_vcenter_host
from vcenter_event_assistant.settings import Settings

router = APIRouter(prefix="/vcenters", tags=["vcenters"])


def _ensure_password_storage_allowed(settings: Settings) -> None:
    if not passwords_may_be_stored(settings):
        raise HTTPException(
            status_code=503,
            detail=(
                "vCenter パスワードを保存できません。VEA_SECRET_KEY を設定するか、"
                "開発環境では VEA_ALLOW_PLAINTEXT_PASSWORDS=1 を設定してください。"
            ),
        )


def _validate_vcenter_host_for_settings(host: str, settings: Settings) -> str:
    try:
        return validate_vcenter_host(
            host,
            allowed_suffixes=settings.vcenter_allowed_host_suffix_list or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[VCenterRead])
async def list_vcenters(
    session: AsyncSession = Depends(get_session),
) -> list[VCenter]:
    res = await session.execute(select(VCenter).order_by(VCenter.name))
    return list(res.scalars().all())


@router.post("", response_model=VCenterRead, status_code=status.HTTP_201_CREATED)
async def create_vcenter(
    body: VCenterCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> VCenter:
    _ensure_password_storage_allowed(settings)
    validated_host = _validate_vcenter_host_for_settings(body.host, settings)
    vc = VCenter(
        name=body.name,
        host=validated_host,
        protocol=body.protocol,
        port=body.port,
        username=body.username,
        password=body.password,
        verify_ssl=body.verify_ssl,
        is_enabled=body.is_enabled,
    )
    session.add(vc)
    await session.flush()
    await session.refresh(vc)
    return vc


@router.get("/{vcenter_id}", response_model=VCenterRead)
async def get_vcenter(
    vcenter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> VCenter:
    res = await session.execute(select(VCenter).where(VCenter.id == vcenter_id))
    vc = res.scalar_one_or_none()
    if vc is None:
        raise HTTPException(status_code=404, detail="vCenter not found")
    return vc


@router.patch("/{vcenter_id}", response_model=VCenterRead)
async def update_vcenter(
    vcenter_id: uuid.UUID,
    body: VCenterUpdate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> VCenter:
    res = await session.execute(select(VCenter).where(VCenter.id == vcenter_id))
    vc = res.scalar_one_or_none()
    if vc is None:
        raise HTTPException(status_code=404, detail="vCenter not found")
    data = body.model_dump(exclude_unset=True)
    if "password" in data:
        _ensure_password_storage_allowed(settings)
    if "host" in data and data["host"] is not None:
        data["host"] = _validate_vcenter_host_for_settings(data["host"], settings)
    for k, v in data.items():
        setattr(vc, k, v)
    await session.flush()
    await session.refresh(vc)
    return vc


@router.delete("/{vcenter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vcenter(
    vcenter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    res = await session.execute(select(VCenter).where(VCenter.id == vcenter_id))
    vc = res.scalar_one_or_none()
    if vc is None:
        raise HTTPException(status_code=404, detail="vCenter not found")
    await session.delete(vc)


@router.get("/{vcenter_id}/test")
async def test_vcenter(
    vcenter_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    res = await session.execute(select(VCenter).where(VCenter.id == vcenter_id))
    vc = res.scalar_one_or_none()
    if vc is None:
        raise HTTPException(status_code=404, detail="vCenter not found")

    try:
        _validate_vcenter_host_for_settings(vc.host, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if settings.mock_mode:
        from vcenter_event_assistant.mocks.mock_connection import mock_connection_info

        info = mock_connection_info()
    else:

        def _run():
            si = connect_vcenter(
                host=vc.host,
                protocol=vc.protocol,
                port=vc.port,
                username=vc.username,
                password=vc.password,
                proxy_url=settings.vcenter_http_proxy,
                verify_ssl=vc.verify_ssl,
                ca_bundle_path=settings.vcenter_ca_bundle,
            )
            try:
                return read_connection_info(si)
            finally:
                disconnect(si)

        try:
            info = await asyncio.to_thread(_run)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=format_connection_error_detail(
                    protocol=vc.protocol,
                    host=vc.host,
                    port=vc.port,
                    exc=exc,
                ),
            ) from exc

    response: dict = {
        "ok": True,
        "product_name": info.product_name,
        "product_version": info.product_version,
        "api_version": info.api_version,
        "instance_uuid": info.instance_uuid,
    }
    if vc.protocol == "https" and not vc.verify_ssl:
        response["recommend_ssl_verification"] = True
        response["recommend_ssl_verification_message"] = (
            "本番環境では SSL 証明書検証（verify_ssl）を有効にすることを推奨します。"
        )
    return response
