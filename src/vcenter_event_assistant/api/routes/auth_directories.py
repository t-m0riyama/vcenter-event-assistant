"""認証ディレクトリ（AD / LDAP）の管理（``/api/auth/directories``、admin のみ）。

- サービスアカウントのパスワードは書き込み専用（応答には ``has_bind_password`` だけを返す）
- 証明書を検証しない設定は保存時に監査ログへ警告を残す。``VEA_DIRECTORY_ALLOW_INSECURE_TLS=false`` なら拒否する
- 本番では暗号化しない接続（``transport_security=none``）を拒否する
- 無効化・削除では、そのディレクトリのユーザーのセッションを失効させる。ログインできる admin が
  いなくなる無効化・削除は断る
- 削除できるのは無効にしたディレクトリだけ。配下のユーザーも削除する
- ユーザーの ID に使う属性（``unique_id_attribute``）は、そのディレクトリのユーザーがいる間は変えられない
"""

from __future__ import annotations

import logging
import re
import ssl
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
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
from vcenter_event_assistant.auth.directory.role_mapping import is_valid_dn, normalize_dn
from vcenter_event_assistant.auth.directory.runner import connect_options, run_directory_call
from vcenter_event_assistant.auth.directory.spec import DEFAULT_UNIQUE_ID_ATTRIBUTE, realm_key_for, spec_from_model
from vcenter_event_assistant.auth.directory.testing import run_test
from vcenter_event_assistant.auth.roles import Role
from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.auth.users import (
    admin_change_guard,
    count_admin_directories,
    count_local_admins,
)
from vcenter_event_assistant.db.models import AuthSession, DirectoryConfig, DirectoryGroupRoleMapping, User
from vcenter_event_assistant.settings import Settings

router = APIRouter(
    prefix="/api/auth/directories",
    tags=["auth"],
    dependencies=[Depends(require_admin)],
)

# 空文字を「未設定」として扱う任意の文字列項目
# 変えても、ログイン中のユーザーの認証・ロールの根拠には影響しない項目。
# これ以外（接続先・TLS・ユーザー検索・グループの調べ方）が変わったら、ログイン中のセッションを失効させる
_SESSION_NEUTRAL_FIELDS = frozenset(
    {"name", "sort_order", "timeout_seconds", "bind_password", "display_name_attribute", "email_attribute"}
)
_IDENTITY_FIELDS = tuple(
    name for name in DirectoryUpdate.model_fields if name not in _SESSION_NEUTRAL_FIELDS | {"is_enabled", "clear_bind_password"}
)

_OPTIONAL_TEXT_FIELDS = (
    "ca_cert_pem",
    "bind_dn",
    "user_search_filter",
    "username_attribute",
    "unique_id_attribute",
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


_DUPLICATE_NAME_MESSAGE = "同じ名前のディレクトリが既にあります。"


def _is_duplicate_name(exc: IntegrityError) -> bool:
    """ディレクトリ名の一意制約の違反か（SQLite は列名、PostgreSQL は制約名がメッセージに入る）。"""
    message = f"{exc} {getattr(exc, 'orig', '')}".lower()
    return "directory_configs.name" in message or "directory_configs_name_key" in message


async def _flush_checking_name(db: AsyncSession) -> None:
    """書き込みを確定する。名前の確認の後に並行したリクエストが同じ名前を確定させていたら 422 にする。"""
    try:
        await db.flush()
    except IntegrityError as exc:
        if _is_duplicate_name(exc):
            raise _invalid(_DUPLICATE_NAME_MESSAGE) from exc
        raise


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
        # 資格情報は URI に入れさせない（ユーザー名が空でパスワードだけのものも。保存され、応答にも出てしまう）
        and parsed.username is None
        and parsed.password is None
        and (port is None or 0 < port < 65536)
    )


# 属性の名前（RFC 4512 の descr）か、数字の OID
_ATTRIBUTE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9-]*|(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))+")


def _effective_unique_id_attribute(value: str | None) -> str:
    """ID 属性の実効値（未設定は entryUUID）。属性名は大文字小文字を区別しないので casefold して比べる。"""
    return (value or DEFAULT_UNIQUE_ID_ATTRIBUTE).casefold()


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
    if config.unique_id_attribute:
        if config.kind == "ad":
            raise _invalid("AD ではユーザーの ID に objectGUID を使うため、ID 属性は指定できません。")
        if not _ATTRIBUTE_NAME.fullmatch(config.unique_id_attribute):
            raise _invalid("ID 属性には属性名（例: nsUniqueId）か数字の OID を指定してください。")
    if config.kind == "ad" and config.group_mode == "group_search":
        raise _invalid("AD ではグループの判定に ad_nested か member_of を使ってください。")
    if config.kind == "ldap" and config.group_mode == "ad_nested":
        raise _invalid("ad_nested は AD でだけ使えます。")
    if config.group_mode == "group_search" and not config.group_search_base:
        raise _invalid("group_search ではグループの検索ベースを指定してください。")


# DirectoryGroupRoleMapping.group_dn_normalized の列長
GROUP_DN_NORMALIZED_MAX_LENGTH = 1024


def _mapping_rows(mappings: list[GroupRoleMappingIn]) -> list[DirectoryGroupRoleMapping]:
    """対応表の行を作る（DN の重複は正規化した値で判定する）。"""
    seen: set[str] = set()
    rows: list[DirectoryGroupRoleMapping] = []
    for m in mappings:
        group_dn = m.group_dn.strip()
        if not group_dn:
            raise _invalid("グループの DN を入力してください。")
        # 解析できない DN はどのグループとも一致しないのに、admin の対応として「使える admin」に数えられてしまう
        if not is_valid_dn(group_dn):
            raise _invalid(f"グループの DN の形式が正しくありません: {group_dn}")
        normalized = normalize_dn(group_dn)
        if len(normalized) > GROUP_DN_NORMALIZED_MAX_LENGTH:
            # 大文字小文字をそろえると文字数が増えることがある（例: U+0390 は 3 文字になる）
            raise _invalid(f"グループの DN が長すぎます: {group_dn[:100]}")
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
        unique_id_attribute=config.unique_id_attribute,
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
    return local + await count_admin_directories(db, connect_options(settings), exclude_directory_id=directory_id)


def _no_admin_left(action: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"{action}と、管理者としてログインできる手段がなくなります（管理者がいなくなります）。",
    )


async def _touch(db: AsyncSession, config: DirectoryConfig) -> None:
    """設定の更新時刻を進めて書き込む。

    認証中のログインは、この時刻が変わっていたら拒否する。失効させる前に書き込んで行をロックし、
    ログイン中の処理が作るセッションも、その確定を待ってから失効の対象に含める。
    """
    config.updated_at = utcnow()
    await db.flush()


async def _revoke_directory_sessions(db: AsyncSession, directory_id: uuid.UUID) -> None:
    """ディレクトリのユーザーのセッションをすべて失効させる（ユーザーが多くても 1 回の DELETE で済ませる）。"""
    users = select(User.id).where(User.directory_id == directory_id)
    await db.execute(delete(AuthSession).where(AuthSession.user_id.in_(users)))


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
    if not data["user_search_base"]:
        raise _invalid("ユーザーの検索ベースを入力してください。")
    for key in (*_OPTIONAL_TEXT_FIELDS, "bind_password"):
        data[key] = _clean(data[key]) if key != "bind_password" else (data[key] or None)
    if not data["server_uris"]:
        raise _invalid("サーバの URI を 1 つ以上指定してください。")
    if await db.scalar(select(DirectoryConfig.id).where(DirectoryConfig.name == data["name"])):
        raise _invalid(_DUPLICATE_NAME_MESSAGE)
    now = utcnow()
    config = DirectoryConfig(**data, created_at=now, updated_at=now)
    config.mappings = _mapping_rows(body.mappings)
    _validate(config, settings)
    db.add(config)
    await _flush_checking_name(db)
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
        identity_before = {name: getattr(config, name) for name in _IDENTITY_FIELDS}
        unique_id_before = config.unique_id_attribute
        if "name" in changes:
            name = (changes["name"] or "").strip()
            if not name:
                raise _invalid("名前を入力してください。")
            duplicate = await db.scalar(
                select(DirectoryConfig.id).where(DirectoryConfig.name == name, DirectoryConfig.id != config.id)
            )
            if duplicate:
                raise _invalid(_DUPLICATE_NAME_MESSAGE)
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
        # 名前の変更を先に書き込む。この後のクエリ（autoflush）や失効のための書き込みで一意制約に反しても、
        # 500 ではなく 422 にするため
        await _flush_checking_name(db)
        if _effective_unique_id_attribute(config.unique_id_attribute) != _effective_unique_id_attribute(
            unique_id_before
        ) and await db.scalar(select(func.count()).select_from(User).where(User.directory_id == config.id)):
            # ID 属性を変えると全員の subject が変わり、無効にしたユーザーが新しい有効な行として作り直される。
            # 変更を書き込んで（行をロックして）から数えるので、並行するログインは先に確定していれば数に入り、
            # 後なら設定の変更（updated_at）を見て拒否される
            raise _invalid(
                "このディレクトリのユーザーがいるため、ID 属性は変更できません。先にユーザーを削除してください。"
            )
        if was_enabled and not config.is_enabled:
            if await _other_admin_sources(db, settings, config.id) == 0:
                raise _no_admin_left("このディレクトリを無効にする")
            # 無効にしたディレクトリのユーザーは、使用中のセッションも使えなくする
            await _touch(db, config)
            await _revoke_directory_sessions(db, config.id)
        elif any(getattr(config, name) != value for name, value in identity_before.items()):
            # 接続先や検索・グループの条件が変わったら、古い条件で認証・ロールを決めたセッションは使わせない
            # （新しい条件ではユーザーが見つからない・ロールが変わることがある）。次のログインで決め直す
            await _touch(db, config)
            await _revoke_directory_sessions(db, config.id)
        config.updated_at = utcnow()
        await _flush_checking_name(db)
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
        # ロールはログインのたびに対応表で決めるので、ログイン中のユーザーは失効させてログインし直させる
        # （対応を外した・弱めたロールのまま使い続けさせない）
        await _touch(db, config)
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
