"""収集と診断の設定で共通の経路。"""

import asyncio
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.settings import Settings


class FeatureGatedRoute(APIRoute):
    """要求本文を読む前に、無効な機能の経路を 404 で隠す。"""

    settings_flag: Literal["plugin_management_enabled", "diagnostics_enabled"]

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def gated_handler(request: Request):
            if not getattr(get_app_settings(), self.settings_flag):
                raise HTTPException(404, "Not Found")
            return await handler(request)

        return gated_handler


class PluginManagementRoute(FeatureGatedRoute):
    settings_flag = "plugin_management_enabled"


class SafeSetupRoute(APIRoute):
    """入力の検証エラーからアップロードした秘密情報を除く。"""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={"detail": "入力の形式を確認してください。"},
                )

        return safe_handler


class PluginSetupRoute(PluginManagementRoute, SafeSetupRoute):
    pass


class DiagnosticsSetupRoute(FeatureGatedRoute, SafeSetupRoute):
    settings_flag = "diagnostics_enabled"


async def list_hosts(
    identifier: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    from vcenter_event_assistant.collectors.connection import (
        VCenterProtocolPolicyError,
        connect_vcenter,
        disconnect,
    )
    from vcenter_event_assistant_plugin_api.vmware import container_view

    vc = await session.get(VCenter, identifier)
    if not vc or not vc.is_enabled:
        raise HTTPException(422, "有効なvCenterを選択してください。")
    if settings.mock_mode:
        return [
            {"id": "mock-esxi", "name": "mock-esxi.local", "host": "mock-esxi.local"}
        ]

    def fetch():
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
            with container_view(si, ["HostSystem"]) as hosts:
                return [
                    {"id": str(h._moId), "name": str(h.name), "host": str(h.name)}
                    for h in hosts
                ]
        finally:
            disconnect(si)

    try:
        return await asyncio.to_thread(fetch)
    except VCenterProtocolPolicyError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        raise HTTPException(
            422,
            "ESXi一覧を取得できません。vCenterの接続設定・参照権限を確認するか、ホスト名を手入力してください。",
        ) from None
