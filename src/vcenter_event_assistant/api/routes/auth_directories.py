"""認証ディレクトリ（AD / LDAP）の管理（``/api/auth/directories``、admin のみ）。

- サービスアカウントのパスワードは書き込み専用（応答には ``has_bind_password`` だけを返す）
- 証明書を検証しない設定は保存時に監査ログへ警告を残す。``VEA_DIRECTORY_ALLOW_INSECURE_TLS=false`` なら拒否する
- 本番では暗号化しない接続（``transport_security=none``）を拒否する
- 無効化・削除では、そのディレクトリのユーザーのセッションを失効させる。ログインできる admin が
  いなくなる無効化・削除は断る
- 削除できるのは無効にしたディレクトリだけ。配下のユーザーも削除する
"""

from __future__ import annotations

import logging
import ssl
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vcenter_event_assistant.api.auth_deps import Principal, require_admin
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.import_guards import HTTP_422
from vcenter_event_assistant.api.schemas.auth_directories import (
    DirectoryCreate,
    DirectoryMappingsUpdate,
    DirectoryRead,
    DirectoryTestRequest,
    DirectoryTestResponse,
    DirectoryTestStage,
    DirectoryUpdate,
    GroupRoleMappingIn,
    GroupRoleMappingRead,
)
from vcenter_event_assistant.auth.audit import audit
from vcenter_event_assistant.auth.directory.role_mapping import normalize_dn
from vcenter_event_assistant.auth.directory.runner import connect_options, run_directory_call
from vcenter_event_assistant.auth.directory.spec import realm_key_for, spec_from_model
from vcenter_event_assistant.auth.directory.testing import run_test
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.auth.sessions import revoke_all_for_user
from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.auth.users import (
    admin_change_guard,
    count_admin_directories,
    count_local_admins,
)
from vcenter_event_assistant.db.models import DirectoryConfig, DirectoryGroupRoleMapping, User
from vcenter_event_assistant.settings import Settings

router = APIRouter(
    prefix="/api/auth/directories",
    tags=["auth"],
    dependencies=[Depends(require_admin)],
)

# 空文字を「未設定」として扱う任意の文字列項目
_OPTIONAL_TEXT_FIELDS = (
    "ca_cert_pem",
    "bind_dn",
    "user_search_filter",
    "username_attribute",
    "ad_upn_suffix",
    "display_name_attribute",
    "email_attribute",
    "group_search_base",
    "group_search_filter",
    "group_member_attribute",
)


def _invalid(message: str) -> HTTPException:
    return HTTPException(status_code=HTTP_422, detail=message)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ディレクトリが見つかりません。")


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _valid_server_uri(uri: str, scheme: str) -> bool:
    """``ldap(s)://host[:port]`` の形か（ldap3 の Server はこの URI からホスト・ポート・SSL を読み取る）。"""
    try:
        parsed = urlsplit(uri)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == scheme
        and bool(parsed.hostname)
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and (port is None or 0 < port < 65536)
    )


def _validate(config: DirectoryConfig, settings: Settings) -> None:
    """保存する前に設定の組み合わせを確かめる。不正なら 422。"""
    if config.transport_security == "none" and settings.is_production:
        raise _invalid("本番環境では暗号化しない接続（none）は使えません。LDAPS か StartTLS を選んでください。")
    if config.transport_security != "none" and not config.tls_verify and not settings.directory_allow_insecure_tls:
        raise _invalid(
            "証明書を検証しない設定は禁止されています（VEA_DIRECTORY_ALLOW_INSECURE_TLS=false）。"
            "CA 証明書を設定してください。"
        )
    expected_scheme = "ldaps" if config.transport_security == "ldaps" else "ldap"
    for uri in config.server_uris:
        if not _valid_server_uri(uri, expected_scheme):
            raise _invalid(
                f"サーバは {expected_scheme}://ホスト名[:ポート] の形で指定してください（パスやクエリは付けない）: {uri}"
            )
    if config.ca_cert_pem:
        if "BEGIN CERTIFICATE" not in config.ca_cert_pem:
            raise _invalid("CA 証明書は PEM 形式（-----BEGIN CERTIFICATE-----）で指定してください。")
        try:
            ssl.create_default_context(cadata=config.ca_cert_pem)
        except (ssl.SSLError, ValueError):
            raise _invalid("CA 証明書を読み込めません。PEM 形式の証明書か確かめてください。") from None
    if config.bind_dn and not config.bind_password:
        raise _invalid("サービスアカウントの DN を指定したときはパスワードも設定してください。")
    if config.kind == "ldap" and config.user_search_filter and "{username}" not in config.user_search_filter:
        raise _invalid("ユーザー検索フィルタには {username} を含めてください。")
    if config.kind == "ad" and config.group_mode == "group_search":
        raise _invalid("AD ではグループの判定に ad_nested か member_of を使ってください。")
    if config.kind == "ldap" and config.group_mode == "ad_nested":
        raise _invalid("ad_nested は AD でだけ使えます。")
    if config.group_mode == "group_search" and not config.group_search_base:
        raise _invalid("group_search ではグループの検索ベースを指定してください。")


def _mapping_rows(mappings: list[GroupRoleMappingIn]) -> list[DirectoryGroupRoleMapping]:
    """対応表の行を作る（DN の重複は正規化した値で判定する）。"""
    seen: set[str] = set()
    rows: list[DirectoryGroupRoleMapping] = []
    for m in mappings:
        group_dn = m.group_dn.strip()
        normalized = normalize_dn(group_dn)
        if not group_dn:
            raise _invalid("グループの DN を入力してください。")
        if normalized in seen:
            raise _invalid(f"同じグループが重複しています: {group_dn}")
        seen.add(normalized)
        rows.append(
            DirectoryGroupRoleMapping(group_dn=group_dn, group_dn_normalized=normalized, role=m.role.value)
        )
    return rows


async def _load(db: AsyncSession, directory_id: uuid.UUID) -> DirectoryConfig:
    config = await db.scalar(
        select(DirectoryConfig)
        .where(DirectoryConfig.id == directory_id)
        .options(selectinload(DirectoryConfig.mappings))
        .execution_options(populate_existing=True)
    )
    if config is None:
        raise _not_found()
    return config


async def _user_counts(db: AsyncSession) -> dict[uuid.UUID, int]:
    rows = await db.execute(
        select(User.directory_id, func.count()).where(User.directory_id.is_not(None)).group_by(User.directory_id)
    )
    return {directory_id: int(count) for directory_id, count in rows.all() if directory_id is not None}


def _to_read(config: DirectoryConfig, user_count: int) -> DirectoryRead:
    return DirectoryRead(
        id=config.id,
        name=config.name,
        kind=config.kind,
        is_enabled=config.is_enabled,
        sort_order=config.sort_order,
        server_uris=list(config.server_uris or []),
        transport_security=config.transport_security,
        tls_verify=config.tls_verify,
        ca_cert_pem=config.ca_cert_pem,
        bind_dn=config.bind_dn,
        has_bind_password=bool(config.bind_password),
        timeout_seconds=config.timeout_seconds,
        user_search_base=config.user_search_base,
        user_search_filter=config.user_search_filter,
        username_attribute=config.username_attribute,
        ad_upn_suffix=config.ad_upn_suffix,
        display_name_attribute=config.display_name_attribute,
        email_attribute=config.email_attribute,
        group_mode=config.group_mode,
        group_search_base=config.group_search_base,
        group_search_filter=config.group_search_filter,
        group_member_attribute=config.group_member_attribute,
        group_member_value=config.group_member_value,
        mappings=[GroupRoleMappingRead(group_dn=m.group_dn, role=Role(m.role)) for m in config.mappings],
        user_count=user_count,
        created_at=as_utc(config.created_at),
        updated_at=as_utc(config.updated_at),
    )


def _audit_saved(event: str, principal: Principal, config: DirectoryConfig) -> None:
    audit(
        event,
        actor=principal.username,
        directory=config.name,
        kind=config.kind,
        enabled=config.is_enabled,
        transport=config.transport_security,
        tls_verify=config.tls_verify,
    )
    if config.transport_security != "none" and not config.tls_verify:
        audit(
            "directory_tls_verify_disabled",
            level=logging.WARNING,
            actor=principal.username,
            directory=config.name,
        )
    if config.transport_security == "none":
        audit(
            "directory_transport_unencrypted",
            level=logging.WARNING,
            actor=principal.username,
            directory=config.name,
        )


async def _other_admin_sources(db: AsyncSession, settings: Settings, directory_id: uuid.UUID) -> int:
    """このディレクトリ以外で admin としてログインできる手段の数（ローカルログインが有効なときの
    ローカルの admin と、admin の対応を持つほかの有効なディレクトリ）。"""
    local = await count_local_admins(db) if settings.local_login_enabled else 0
    return local + await count_admin_directories(db, exclude_directory_id=directory_id)


def _no_admin_left(action: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"{action}と、管理者としてログインできる手段がなくなります（管理者がいなくなります）。",
    )


async def _revoke_directory_sessions(db: AsyncSession, directory_id: uuid.UUID) -> None:
    user_ids = (await db.scalars(select(User.id).where(User.directory_id == directory_id))).all()
    for user_id in user_ids:
        await revoke_all_for_user(db, user_id)


@router.get("", response_model=list[DirectoryRead])
async def list_directories(db: AsyncSession = Depends(get_session)) -> list[DirectoryRead]:
    rows = (
        await db.scalars(
            select(DirectoryConfig)
            .options(selectinload(DirectoryConfig.mappings))
            .order_by(DirectoryConfig.sort_order, DirectoryConfig.name)
        )
    ).all()
    counts = await _user_counts(db)
    return [_to_read(d, counts.get(d.id, 0)) for d in rows]


@router.post("", response_model=DirectoryRead, status_code=status.HTTP_201_CREATED)
async def create_directory(
    body: DirectoryCreate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> DirectoryRead:
    data = body.model_dump(exclude={"mappings"})
    data["name"] = data["name"].strip()
    if not data["name"]:
        raise _invalid("名前を入力してください。")
    data["server_uris"] = [u.strip() for u in data["server_uris"] if u.strip()]
    data["user_search_base"] = data["user_search_base"].strip()
    for key in (*_OPTIONAL_TEXT_FIELDS, "bind_password"):
        data[key] = _clean(data[key]) if key != "bind_password" else (data[key] or None)
    if not data["server_uris"]:
        raise _invalid("サーバの URI を 1 つ以上指定してください。")
    if await db.scalar(select(DirectoryConfig.id).where(DirectoryConfig.name == data["name"])):
        raise _invalid("同じ名前のディレクトリが既にあります。")
    now = utcnow()
    config = DirectoryConfig(**data, created_at=now, updated_at=now)
    config.mappings = _mapping_rows(body.mappings)
    _validate(config, settings)
    db.add(config)
    await db.flush()
    _audit_saved("directory_created", principal, config)
    return _to_read(config, 0)


@router.patch("/{directory_id}", response_model=DirectoryRead)
async def update_directory(
    directory_id: uuid.UUID,
    body: DirectoryUpdate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> DirectoryRead:
    changes = body.model_dump(exclude_unset=True, exclude={"clear_bind_password"})
    async with admin_change_guard(db):
        config = await _load(db, directory_id)
        was_enabled = config.is_enabled
        if "name" in changes:
            name = (changes["name"] or "").strip()
            if not name:
                raise _invalid("名前を入力してください。")
            duplicate = await db.scalar(
                select(DirectoryConfig.id).where(DirectoryConfig.name == name, DirectoryConfig.id != config.id)
            )
            if duplicate:
                raise _invalid("同じ名前のディレクトリが既にあります。")
            changes["name"] = name
        if "server_uris" in changes and changes["server_uris"] is not None:
            changes["server_uris"] = [u.strip() for u in changes["server_uris"] if u.strip()]
            if not changes["server_uris"]:
                raise _invalid("サーバの URI を 1 つ以上指定してください。")
        if "user_search_base" in changes:
            changes["user_search_base"] = _clean(changes["user_search_base"])
            if not changes["user_search_base"]:
                raise _invalid("ユーザーの検索ベースを入力してください。")
        new_password = changes.pop("bind_password", None)
        for key, value in changes.items():
            if value is None and key not in _OPTIONAL_TEXT_FIELDS and key != "group_member_value":
                continue  # 必須項目の null は「変えない」と同じ
            setattr(config, key, _clean(value) if key in _OPTIONAL_TEXT_FIELDS else value)
        if body.clear_bind_password:
            config.bind_password = None
        elif new_password:
            config.bind_password = new_password
        _validate(config, settings)
        if was_enabled and not config.is_enabled:
            if await _other_admin_sources(db, settings, config.id) == 0:
                raise _no_admin_left("このディレクトリを無効にする")
            # 無効にしたディレクトリのユーザーは、使用中のセッションも使えなくする
            await _revoke_directory_sessions(db, config.id)
        config.updated_at = utcnow()
        await db.flush()
        user_count = (await _user_counts(db)).get(config.id, 0)
        result = _to_read(config, user_count)
    _audit_saved("directory_updated", principal, config)
    return result


@router.put("/{directory_id}/mappings", response_model=DirectoryRead)
async def replace_mappings(
    directory_id: uuid.UUID,
    body: DirectoryMappingsUpdate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> DirectoryRead:
    rows = _mapping_rows(body.mappings)
    async with admin_change_guard(db):
        config = await _load(db, directory_id)
        had_admin = any(m.role == Role.ADMIN.value for m in config.mappings)
        keeps_admin = any(r.role == Role.ADMIN.value for r in rows)
        if (
            config.is_enabled
            and had_admin
            and not keeps_admin
            and await _other_admin_sources(db, settings, config.id) == 0
        ):
            raise _no_admin_left("admin の対応をなくす")
        # 古い行を先に消して確定させる（同じグループを残すと、追加が先に走って一意制約に反するため）
        config.mappings.clear()
        await db.flush()
        config.mappings = rows
        config.updated_at = utcnow()
        # ロールはログインのたびに対応表で決めるので、ログイン中のユーザーは失効させてログインし直させる
        # （対応を外した・弱めたロールのまま使い続けさせない）
        await _revoke_directory_sessions(db, config.id)
        await db.flush()
    audit(
        "directory_mappings_updated",
        actor=principal.username,
        directory=config.name,
        mappings=len(config.mappings),
    )
    return _to_read(config, (await _user_counts(db)).get(config.id, 0))


@router.delete("/{directory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_directory(
    directory_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    async with admin_change_guard(db):
        config = await _load(db, directory_id)
        if config.is_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="有効なディレクトリは削除できません。先に無効にしてください。",
            )
        if await _other_admin_sources(db, settings, config.id) == 0:
            raise _no_admin_left("このディレクトリを削除する")
        name = config.name
        # 配下のユーザー（とセッション）も消す。users.directory_id には外部キーがないので明示的に消す
        removed = await db.execute(delete(User).where(User.directory_id == config.id))
        await db.delete(config)
        await db.flush()
    audit("directory_deleted", actor=principal.username, directory=name, users_deleted=removed.rowcount)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{directory_id}/test", response_model=DirectoryTestResponse)
async def test_directory(
    directory_id: uuid.UUID,
    body: DirectoryTestRequest,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> DirectoryTestResponse:
    """保存済みの設定で接続を試す（無効のディレクトリでも試せる）。"""
    config = await _load(db, directory_id)
    spec = spec_from_model(config)
    stages = await run_directory_call(
        run_test,
        spec,
        connect_options(settings),
        username=(body.username or None),
        password=(body.password or None),
    )
    audit(
        "directory_tested",
        actor=principal.username,
        directory=config.name,
        ok=all(s.ok for s in stages),
        realm=realm_key_for(config.id),
    )
    return DirectoryTestResponse(
        ok=all(s.ok for s in stages),
        stages=[DirectoryTestStage(stage=s.stage, ok=s.ok, message=s.message) for s in stages],
    )
