"""ユーザー管理（``/api/auth/users``、admin のみ）。

ロール変更・無効化・パスワード再設定・削除では、対象ユーザーのセッションを全部失効させる。
最後の有効な admin は降格・無効化・削除できない。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.auth_deps import Principal, require_admin
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.import_guards import HTTP_422
from vcenter_event_assistant.api.schemas.auth import (
    AdminPasswordReset,
    UserCreate,
    UserRead,
    UserUpdate,
)
from vcenter_event_assistant.auth.audit import audit
from vcenter_event_assistant.auth.passwords import PasswordPolicyError
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.auth.sessions import revoke_all_for_user
from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.auth.users import (
    LOCAL_REALM,
    DISPLAY_NAME_MAX_LENGTH,
    EMAIL_MAX_LENGTH,
    LastAdminError,
    UserError,
    admin_change_guard,
    create_local_user,
    ensure_not_last_admin,
    normalize_optional_text,
    set_local_password,
    unlock_user,
)
from vcenter_event_assistant.db.models import User
from vcenter_event_assistant.settings import Settings

router = APIRouter(
    prefix="/api/auth/users",
    tags=["auth"],
    dependencies=[Depends(require_admin)],
)


def _to_read(user: User) -> UserRead:
    locked_until = as_utc(user.locked_until) if user.locked_until else None
    return UserRead(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=Role(user.role),
        realm=user.realm_key,
        is_local=user.realm_key == LOCAL_REALM,
        is_active=user.is_active,
        locked=locked_until is not None and locked_until > utcnow(),
        locked_until=locked_until,
        last_login_at=as_utc(user.last_login_at) if user.last_login_at else None,
        created_at=as_utc(user.created_at),
    )


def _bad_request(message: str) -> HTTPException:
    # 管理画面に理由（パスワードの要件・重複など）を見せるため 422 にする（画面は 400 の本文を出さない）
    return HTTPException(status_code=HTTP_422, detail=message)


async def _get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    # 認証時に同じセッションへ読み込まれた行が古いまま返らないよう、DB から読み直す
    user = await db.get(User, user_id, populate_existing=True)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ユーザーが見つかりません。")
    return user


def _conflict(exc: LastAdminError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _actor(principal: Principal) -> str:
    return principal.username


@router.get("", response_model=list[UserRead])
async def list_users(db: AsyncSession = Depends(get_session)) -> list[UserRead]:
    rows = (await db.scalars(select(User).order_by(User.realm_key, User.username))).all()
    return [_to_read(u) for u in rows]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> UserRead:
    try:
        user = await create_local_user(
            db,
            username=body.username,
            password=body.password,
            role=body.role,
            password_min_length=settings.password_min_length,
            display_name=body.display_name,
            email=body.email,
        )
    except (UserError, PasswordPolicyError) as exc:
        raise _bad_request(str(exc)) from None
    audit("user_created", actor=_actor(principal), username=user.username, role=user.role)
    return _to_read(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> UserRead:
    changes = body.model_dump(exclude_unset=True)
    try:
        # 作成時と同じ検査（列長・制御文字）。ロックを取る前に入力エラーを返す
        if "display_name" in changes:
            changes["display_name"] = normalize_optional_text(
                changes["display_name"], max_length=DISPLAY_NAME_MAX_LENGTH, label="表示名"
            )
        if "email" in changes:
            changes["email"] = normalize_optional_text(
                changes["email"], max_length=EMAIL_MAX_LENGTH, label="メールアドレス"
            )
    except UserError as exc:
        raise _bad_request(str(exc)) from None
    revoke = False
    try:
        async with admin_change_guard(db):
            user = await _get_user(db, user_id)
            new_role = changes.get("role")
            if new_role is not None and Role(new_role).value != user.role:
                if user.realm_key != LOCAL_REALM:
                    raise _bad_request("ディレクトリのユーザーのロールはグループの対応表で決まります。")
                if new_role != Role.ADMIN:
                    await ensure_not_last_admin(db, user, local_login_enabled=settings.local_login_enabled)
                user.role = Role(new_role).value
                revoke = True

            new_active = changes.get("is_active")
            if new_active is not None and new_active != user.is_active:
                if not new_active:
                    await ensure_not_last_admin(db, user, local_login_enabled=settings.local_login_enabled)
                # 無効化では使用中のセッションを切り、再有効化では無効化前の（盗まれた可能性の
                # ある）セッションを復活させない。どちらも全セッションを失効させる
                revoke = True
                user.is_active = new_active

            if "display_name" in changes:
                user.display_name = changes["display_name"]
            if "email" in changes:
                user.email = changes["email"]

            user.updated_at = utcnow()
            if revoke:
                await revoke_all_for_user(db, user.id)
            await db.flush()
    except LastAdminError as exc:
        raise _conflict(exc) from None
    audit(
        "user_updated",
        actor=_actor(principal),
        username=user.username,
        role=user.role,
        active=user.is_active,
        sessions_revoked=revoke,
    )
    return _to_read(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    if principal.user_id == user_id:
        raise _bad_request("自分自身は削除できません。")
    try:
        async with admin_change_guard(db):
            user = await _get_user(db, user_id)
            await ensure_not_last_admin(db, user, local_login_enabled=settings.local_login_enabled)
            username = user.username
            await db.delete(user)
            await db.flush()
    except LastAdminError as exc:
        raise _conflict(exc) from None
    audit("user_deleted", actor=_actor(principal), username=username)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: uuid.UUID,
    body: AdminPasswordReset,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    user = await _get_user(db, user_id)
    keep = principal.session_id if principal.user_id == user.id else None
    try:
        await set_local_password(
            db,
            user,
            body.password,
            password_min_length=settings.password_min_length,
            keep_session_id=keep,
        )
    except (UserError, PasswordPolicyError) as exc:
        raise _bad_request(str(exc)) from None
    audit("password_reset", actor=_actor(principal), username=user.username)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/sessions/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_sessions(
    user_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> Response:
    user = await _get_user(db, user_id)
    keep = principal.session_id if principal.user_id == user.id else None
    await revoke_all_for_user(db, user.id, except_session_id=keep)
    audit("sessions_revoked", actor=_actor(principal), username=user.username)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/unlock", response_model=UserRead)
async def unlock(
    user_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> UserRead:
    user = await _get_user(db, user_id)
    unlock_user(user)
    await db.flush()
    audit("user_unlocked", actor=_actor(principal), username=user.username)
    return _to_read(user)
