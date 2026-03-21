"""Minimal auth: Bearer token and/or HTTP Basic."""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer
from starlette.requests import Request

from vcenter_event_assistant.settings import get_settings

_bearer = HTTPBearer(auto_error=False)
_basic = HTTPBasic(auto_error=False)


async def require_auth(
    request: Request,
    bearer_creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    basic_creds: HTTPBasicCredentials | None = Depends(_basic),
) -> None:
    settings = get_settings()
    has_bearer = bool(settings.auth_bearer_token)
    has_basic = bool(settings.auth_basic_username and settings.auth_basic_password)

    if not has_bearer and not has_basic:
        return

    if has_bearer and bearer_creds and secrets.compare_digest(
        bearer_creds.credentials,
        settings.auth_bearer_token or "",
    ):
        return

    if has_basic and basic_creds:
        ok_user = secrets.compare_digest(basic_creds.username, settings.auth_basic_username or "")
        ok_pass = secrets.compare_digest(basic_creds.password, settings.auth_basic_password or "")
        if ok_user and ok_pass:
            return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )
