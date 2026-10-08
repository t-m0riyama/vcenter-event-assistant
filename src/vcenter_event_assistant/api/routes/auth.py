"""ログイン・ログアウト・自分の情報（``/api/auth``）。

この router は保護対象の ``/api`` router とは別にマウントし、ログイン前でも呼べる。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.auth_deps import (
    Principal,
    get_current_principal,
    session_cookie_name,
)
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.schemas.auth import (
    ChangeOwnPasswordRequest,
    LoginRequest,
    MeResponse,
    RealmRead,
    RealmsResponse,
)
from vcenter_event_assistant.auth.audit import audit
from vcenter_event_assistant.auth.passwords import PasswordPolicyError, verify_password
from vcenter_event_assistant.auth.service import (
    GENERIC_LOGIN_ERROR,
    authenticate,
    list_realms,
    session_policy,
)
from vcenter_event_assistant.auth.principal_header import principal_marker
from vcenter_event_assistant.auth.sessions import create_session, revoke_session
from vcenter_event_assistant.auth.tokens import hash_token
from vcenter_event_assistant.auth.users import (
    LOCAL_REALM,
    PasswordChangedConcurrentlyError,
    UserError,
    set_local_password,
)
from vcenter_event_assistant.db.models import AuthSession, User
from vcenter_event_assistant.settings import Settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _activity_interval_seconds(settings: Settings) -> int | None:
    if not settings.auth_enabled:
        return None
    return int(session_policy(settings).touch_interval.total_seconds())


def _me(principal: Principal, *, settings: Settings) -> MeResponse:
    return MeResponse(
        auth_enabled=settings.auth_enabled,
        username=principal.username,
        display_name=principal.display_name,
        role=principal.role.value,
        realm=principal.realm,
        can_change_password=principal.realm == LOCAL_REALM,
        session_activity_interval_seconds=_activity_interval_seconds(settings),
        principal_id=(
            principal_marker(principal.user_id, principal.session_id)
            if principal.user_id and principal.session_id
            else None
        ),
    )


def _require_auth_enabled(settings: Settings) -> None:
    if not settings.auth_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@router.get("/realms", response_model=RealmsResponse)
async def get_realms(
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> RealmsResponse:
    if not settings.auth_enabled:
        return RealmsResponse(auth_enabled=False, realms=[])
    realms = await list_realms(db, settings)
    return RealmsResponse(
        auth_enabled=True,
        realms=[RealmRead(id=r.id, name=r.name, kind=r.kind) for r in realms],
    )


@router.post("/login", response_model=MeResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    _require_auth_enabled(settings)
    client_ip = _client_ip(request)
    outcome = await authenticate(
        db,
        settings,
        realm=body.realm,
        username=body.username,
        password=body.password,
        client_ip=client_ip,
    )
    if outcome.user is None:
        # 例外にすると get_session がロールバックし、失敗回数の記録が消えるため Response で返す
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": GENERIC_LOGIN_ERROR},
        )

    cookie_name = session_cookie_name(settings)
    # セッション固定攻撃対策: 既存のセッションは破棄して必ず新しいトークンを発行する
    await revoke_session(db, request.cookies.get(cookie_name))
    policy = session_policy(settings)
    token = await create_session(
        db,
        outcome.user,
        policy,
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent"),
    )
    user = outcome.user
    session_id = (
        await db.execute(select(AuthSession.id).where(AuthSession.token_hash == hash_token(token)))
    ).scalar_one()
    payload = MeResponse(
        auth_enabled=True,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        realm=user.realm_key,
        can_change_password=user.realm_key == LOCAL_REALM,
        session_activity_interval_seconds=_activity_interval_seconds(settings),
        principal_id=principal_marker(user.id, session_id),
    )
    response = JSONResponse(content=payload.model_dump())
    response.set_cookie(
        cookie_name,
        token,
        max_age=int(policy.absolute_timeout.total_seconds()),
        path="/",
        secure=settings.effective_session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    """未ログインでも成功する（期限切れ後に押されても画面を戻せるように）。"""
    cookie_name = session_cookie_name(settings)
    token = request.cookies.get(cookie_name)
    if settings.auth_enabled and token:
        await revoke_session(db, token)
        audit("logout", ip=_client_ip(request))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        cookie_name,
        path="/",
        secure=settings.effective_session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get("/me", response_model=MeResponse)
async def get_me(
    principal: Principal = Depends(get_current_principal),
    settings: Settings = Depends(get_app_settings),
) -> MeResponse:
    return _me(principal, settings=settings)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_own_password(
    body: ChangeOwnPasswordRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    _require_auth_enabled(settings)
    if principal.realm != LOCAL_REALM or principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ディレクトリのユーザーはこの画面でパスワードを変更できません。",
        )
    user = await db.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ログインが必要です。")
    # この値を条件に更新するので、検証中に別の変更が確定していたら上書きしない
    verified_hash = user.password_hash
    if not (await verify_password(verified_hash, body.current_password)).ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="現在のパスワードが正しくありません。",
        )
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新しいパスワードは現在のものと異なる値にしてください。",
        )
    try:
        await set_local_password(
            db,
            user,
            body.new_password,
            password_min_length=settings.password_min_length,
            keep_session_id=principal.session_id,
            expected_hash=verified_hash,
        )
    except PasswordChangedConcurrentlyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except (PasswordPolicyError, UserError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    audit("password_changed", username=user.username, ip=_client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
