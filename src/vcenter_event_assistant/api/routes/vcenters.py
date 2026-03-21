"""vCenter CRUD and connection test."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import VCenterCreate, VCenterRead, VCenterUpdate
from vcenter_event_assistant.collectors.connection import connect_vcenter, disconnect, read_connection_info
from vcenter_event_assistant.db.models import VCenter

router = APIRouter(prefix="/vcenters", tags=["vcenters"])


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
) -> VCenter:
    vc = VCenter(
        name=body.name,
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password,
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
) -> VCenter:
    res = await session.execute(select(VCenter).where(VCenter.id == vcenter_id))
    vc = res.scalar_one_or_none()
    if vc is None:
        raise HTTPException(status_code=404, detail="vCenter not found")
    data = body.model_dump(exclude_unset=True)
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
) -> dict:
    res = await session.execute(select(VCenter).where(VCenter.id == vcenter_id))
    vc = res.scalar_one_or_none()
    if vc is None:
        raise HTTPException(status_code=404, detail="vCenter not found")

    def _run():
        si = connect_vcenter(host=vc.host, port=vc.port, username=vc.username, password=vc.password)
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
