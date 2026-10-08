"""認証ディレクトリ（AD / LDAP）の管理（``/api/auth/directories``、admin のみ）。

- サービスアカウントのパスワードは書き込み専用（応答には ``has_bind_password`` だけを返す）
- 証明書を検証しない設定は保存時に監査ログへ警告を残す。``VEA_DIRECTORY_ALLOW_INSECURE_TLS=false`` なら拒否する
- 本番では暗号化しない接続（``transport_security=none``）を拒否する
- 無効化・削除では、そのディレクトリのユーザーのセッションを失効させる。ログインできる admin が
  いなくなる無効化・削除は断る。操作している admin が自分のログインしているディレクトリを無効にすることも断る
- 設定と対応表は ``PATCH`` でまとめて保存する（セッションの失効も 1 回にする）。保存で admin としてログイン
  する手段を失うおそれがあるときは、新しい設定で admin としてログインできることを確かめてから保存する
  （Issue #254・Issue #258）
- 接続試験は、保存済みの設定に編集中の変更を重ねても、まだ保存していない設定でも行える（DB には書かない）
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
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vcenter_event_assistant.api.auth_deps import Principal, require_admin
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.import_guards import HTTP_422
from vcenter_event_assistant.api.schemas.auth_directories import (
    DirectoryChanges,
    DirectoryCreate,
    DirectoryCredentials,
    DirectoryPolicy,
    DirectoryRead,
    DirectoryTestRequest,
    DirectoryTestResponse,
    DirectoryTestStage,
    DirectoryTestUnsavedRequest,
    DirectoryUpdate,
    GroupRoleMappingIn,
    GroupRoleMappingRead,
)
from vcenter_event_assistant.auth.audit import audit
from vcenter_event_assistant.auth.directory import backend as directory_backend
from vcenter_event_assistant.auth.directory.backend import DirectoryIdentity
from vcenter_event_assistant.auth.directory.errors import DirectoryError
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
    directory_subject_key,
)
from vcenter_event_assistant.db.models import AuthSession, DirectoryConfig, DirectoryGroupRoleMapping, User
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

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
    name for name in DirectoryChanges.model_fields if name not in _SESSION_NEUTRAL_FIELDS | {"is_enabled", "clear_bind_password"}
)
# セッションは失効させないが、誤るとこの後のログインがすべて失敗する項目（保存の前の確認の対象には含める）
_LOGIN_CRITICAL_NEUTRAL_FIELDS = ("bind_password", "timeout_seconds")
_COLUMN_KEYS = tuple(attr.key for attr in sa_inspect(DirectoryConfig).column_attrs)

# 409 の理由を画面が見分けるためのヘッダ（detail は文字列のまま返す）
ERROR_CODE_HEADER = "X-VEA-Error-Code"
VERIFICATION_REQUIRED = "directory_verification_required"
VERIFICATION_FAILED = "directory_verification_failed"

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


def _audit_saved(event: str, principal: Principal, config: DirectoryConfig, **extra: Any) -> None:
    audit(
        event,
        actor=principal.username,
        directory=config.name,
        kind=config.kind,
        enabled=config.is_enabled,
        transport=config.transport_security,
        tls_verify=config.tls_verify,
        **extra,
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


def _new_config(body: DirectoryCreate) -> DirectoryConfig:
    """作成する（または保存せずに試す）設定。入力が不正なら 422。"""
    data = body.model_dump(include=set(DirectoryCreate.model_fields) - {"mappings"})
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
    now = utcnow()
    config = DirectoryConfig(**data, created_at=now, updated_at=now)
    config.mappings = _mapping_rows(body.mappings)
    return config


def _apply_changes(config: DirectoryConfig, changes: dict[str, Any], *, clear_bind_password: bool) -> None:
    """設定の変更を重ねる（省略した項目と、必須項目の null は変えない）。入力が不正なら 422。"""
    changes = dict(changes)
    if "name" in changes:
        name = (changes["name"] or "").strip()
        if not name:
            raise _invalid("名前を入力してください。")
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
    if clear_bind_password:
        config.bind_password = None
    elif new_password:
        config.bind_password = new_password


def _edited(
    base: DirectoryConfig,
    changes: dict[str, Any],
    *,
    clear_bind_password: bool,
    mappings: list[GroupRoleMappingIn] | None,
    settings: Settings,
) -> DirectoryConfig:
    """保存済みの設定に編集中の変更を重ねた写し（セッションに入れないので、DB には書かれない）。

    試験と、保存の前の確認に使う。``mappings`` が ``None`` なら保存済みの対応表のまま。入力が不正なら 422。
    """
    draft = DirectoryConfig(**{key: getattr(base, key) for key in _COLUMN_KEYS})
    if mappings is not None:
        draft.mappings = _mapping_rows(mappings)
    else:
        draft.mappings = [
            DirectoryGroupRoleMapping(group_dn=m.group_dn, group_dn_normalized=m.group_dn_normalized, role=m.role)
            for m in base.mappings
        ]
    _apply_changes(draft, changes, clear_bind_password=clear_bind_password)
    _validate(draft, settings)
    return draft


def _mapping_set(mappings: list[DirectoryGroupRoleMapping]) -> set[tuple[str, str]]:
    """ロールの決定に効く対応表の中身（登録したままの DN の書き方の違いは含めない）。"""
    return {(m.group_dn_normalized, m.role) for m in mappings}


def _has_admin_mapping(mappings: list[DirectoryGroupRoleMapping]) -> bool:
    return any(m.role == Role.ADMIN.value for m in mappings)


def _identity_changed(config: DirectoryConfig, draft: DirectoryConfig) -> bool:
    """ログイン中のユーザーの認証・ロールの根拠が変わるか（変わればセッションを失効させる）。"""
    return any(getattr(draft, name) != getattr(config, name) for name in _IDENTITY_FIELDS) or _mapping_set(
        draft.mappings
    ) != _mapping_set(config.mappings)


def _login_affected(config: DirectoryConfig, draft: DirectoryConfig) -> bool:
    """この後のログインの成否が変わり得るか（保存の前に確かめるかの判断に使う）。

    セッションを失効させる変更に加え、サービスアカウントのパスワードとタイムアウトも含める。
    これらは失効させないが、誤るとログアウトや期限切れの後に誰もログインできなくなる。
    """
    return _identity_changed(config, draft) or any(
        getattr(draft, name) != getattr(config, name) for name in _LOGIN_CRITICAL_NEUTRAL_FIELDS
    )


def _acting_in(principal: Principal, config: DirectoryConfig) -> bool:
    """操作している admin が、このディレクトリのユーザーとしてログインしているか。"""
    return principal.realm == realm_key_for(config.id)


async def _refuse_losing_admin(
    db: AsyncSession, settings: Settings, principal: Principal, config: DirectoryConfig, draft: DirectoryConfig
) -> None:
    """admin としてログインする手段を確実に失う変更を 409 で断る（確かめるまでもない場合）。"""
    disabling = config.is_enabled and not draft.is_enabled
    dropping_admin = (
        config.is_enabled
        and draft.is_enabled
        and _has_admin_mapping(config.mappings)
        and not _has_admin_mapping(draft.mappings)
    )
    if (disabling or dropping_admin) and await _other_admin_sources(db, settings, config.id) == 0:
        raise _no_admin_left("このディレクトリを無効にする" if disabling else "admin の対応をなくす")
    if disabling and _acting_in(principal, config):
        # 無効にしたディレクトリはログインに使えないので、新しい設定で確かめても安全はわからない。
        # 別の経路で実際にログインして操作していることが、その経路が使える証明になる
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ログインに使っているディレクトリは無効にできません。ローカルや別のディレクトリの admin で"
            "ログインし直してから操作してください。",
        )


async def _verification_needed(
    db: AsyncSession, settings: Settings, principal: Principal, config: DirectoryConfig, draft: DirectoryConfig
) -> bool:
    """保存の前に、新しい設定で admin としてログインできるか確かめる必要があるか。

    ログインの成否に関わる変更（有効化を含む。``_login_affected``）で、次のどちらかに当たるとき:
    (a) 操作している admin がこのディレクトリのユーザー（自分のセッションが失効する、または今のセッションが
        切れた後にログインし直せなくなる）
    (b) 設定上、ほかに admin の経路がない。ほかの経路の数え方は設定と方針しか見ず、サーバが落ちている・
        グループが存在しないなど実際には使えない経路も数えるので、(b) だけでは締め出しを防げない
    """
    if not draft.is_enabled:
        return False
    if config.is_enabled and not _login_affected(config, draft):
        return False
    return _acting_in(principal, config) or await _other_admin_sources(db, settings, config.id) == 0


def _verification_error(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message, headers={ERROR_CODE_HEADER: code})


def _verification_required() -> HTTPException:
    return _verification_error(
        VERIFICATION_REQUIRED,
        "この変更を保存すると、管理者としてログインできなくなるおそれがあります。新しい設定で admin として"
        "ログインできるユーザーの資格情報を入力して、確かめてから保存してください。",
    )


async def _verify_admin(
    draft: DirectoryConfig, credentials: DirectoryCredentials | None, settings: Settings
) -> DirectoryIdentity:
    """新しい設定と対応表で、本番のログインと同じ処理を通し、admin になることを確かめる。

    段階を個別に並べると ID 属性の確認のような段階が抜けるので、ログインの処理そのものを使う。
    """
    if credentials is None:
        raise _verification_required()
    try:
        identity = await run_directory_call(
            directory_backend.authenticate,
            spec_from_model(draft),
            credentials.username,
            credentials.password,
            connect_options(settings),
        )
    except DirectoryError as exc:
        raise _verification_error(
            VERIFICATION_FAILED, f"新しい設定では、入力した資格情報でログインできません: {exc}"
        ) from None
    except Exception:
        logger.exception("Unexpected error while verifying changes to directory %r", draft.name)
        raise _verification_error(VERIFICATION_FAILED, "新しい設定での確認中にエラーが起きました。") from None
    if identity.role != Role.ADMIN:
        raise _verification_error(
            VERIFICATION_FAILED,
            f"新しい設定では、入力したユーザーのロールが {identity.role.value} になり、admin としてログインできません。",
        )
    return identity


async def _refuse_disabled_verifier(db: AsyncSession, config: DirectoryConfig, identity: DirectoryIdentity) -> None:
    """確かめたユーザーがアプリで無効になっていれば 409（ディレクトリの認証は ``is_active`` を見ないため。Issue #258）。

    ``admin_change_guard`` の中で呼ぶ（ユーザーの無効化も同じロックを通るので、読んだ後に無効にされない）。
    行がなければ、初回のログインで有効な行が作られるので通す。
    """
    is_active = await db.scalar(
        select(User.is_active).where(
            User.realm_key == realm_key_for(config.id),
            User.subject == directory_subject_key(identity.subject),
        )
    )
    if is_active is False:
        raise _verification_error(
            VERIFICATION_FAILED,
            "入力したユーザーはこのアプリで無効になっているため、新しい設定でもログインできません。"
            "有効な admin の資格情報で確かめてください。",
        )


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


@router.get("/policy", response_model=DirectoryPolicy)
async def get_policy(settings: Settings = Depends(get_app_settings)) -> DirectoryPolicy:
    # 保存時の検証（_validate）と同じ設定から決める
    return DirectoryPolicy(
        allow_insecure_tls=settings.directory_allow_insecure_tls,
        allow_no_transport_security=not settings.is_production,
    )


@router.post("", response_model=DirectoryRead, status_code=status.HTTP_201_CREATED)
async def create_directory(
    body: DirectoryCreate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> DirectoryRead:
    config = _new_config(body)
    if await db.scalar(select(DirectoryConfig.id).where(DirectoryConfig.name == config.name)):
        raise _invalid(_DUPLICATE_NAME_MESSAGE)
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
    """設定と対応表をまとめて保存する（セッションの失効も 1 回にする）。

    分けて保存すると、1 回目でこのディレクトリのセッションが失効し、唯一の admin が 2 回目を送れなくなる。
    保存で admin としてログインする手段を失うおそれがあるときは、``verification`` の資格情報で、新しい設定の
    もとで admin としてログインできることを確かめてから保存する（できなければ 409）。
    """
    changes = body.model_dump(exclude_unset=True, exclude={"clear_bind_password", "mappings", "verification"})

    def edited(base: DirectoryConfig) -> DirectoryConfig:
        return _edited(
            base, changes, clear_bind_password=body.clear_bind_password, mappings=body.mappings, settings=settings
        )

    # 確認（LDAP の呼び出し）はロックの外で行う。待っている間、admin の変更やこのディレクトリへのログインを
    # 止めないため。その代わり、ロックを取った後で設定が確認した時から変わっていないことを確かめる
    config = await _load(db, directory_id)
    version = config.updated_at
    draft = edited(config)
    await _refuse_losing_admin(db, settings, principal, config, draft)
    verified: DirectoryIdentity | None = None
    if await _verification_needed(db, settings, principal, config, draft):
        await db.rollback()  # 確認の間、読み取りのトランザクションを開いたままにしない
        verified = await _verify_admin(draft, body.verification, settings)

    async with admin_change_guard(db):
        config = await _load(db, directory_id)
        if verified is not None and config.updated_at != version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ほかの操作で設定が変わりました。読み直してから、もう一度保存してください。",
            )
        draft = edited(config)
        await _refuse_losing_admin(db, settings, principal, config, draft)
        if verified is None and await _verification_needed(db, settings, principal, config, draft):
            # 確認した後に、ほかの admin の経路がなくなった
            raise _verification_required()
        if verified is not None:
            await _refuse_disabled_verifier(db, config, verified)

        disabling = config.is_enabled and not draft.is_enabled
        identity_changed = _identity_changed(config, draft)
        unique_id_before = config.unique_id_attribute
        if "name" in changes:
            duplicate = await db.scalar(
                select(DirectoryConfig.id).where(DirectoryConfig.name == draft.name, DirectoryConfig.id != config.id)
            )
            if duplicate:
                raise _invalid(_DUPLICATE_NAME_MESSAGE)
        _apply_changes(config, changes, clear_bind_password=body.clear_bind_password)
        # 名前の変更を先に書き込む。この後のクエリ（autoflush）や失効のための書き込みで一意制約に反しても、
        # 500 ではなく 422 にするため
        await _flush_checking_name(db)
        if _effective_unique_id_attribute(config.unique_id_attribute) != _effective_unique_id_attribute(
            unique_id_before
        ) and await db.scalar(select(func.count()).select_from(User).where(User.directory_id == config.id)):
            # ID 属性を変えると全員の subject が変わり、無効にしたユーザーが新しい有効な行として作り直される。
            # ディレクトリのユーザーは個別に削除できない（無効化で止める）ので、ディレクトリの作り直しを案内する。
            # 変更を書き込んで（行をロックして）から数えるので、並行するログインは先に確定していれば数に入り、
            # 後なら設定の変更（updated_at）を見て拒否される
            raise _invalid(
                "このディレクトリのユーザーがいるため、ID 属性は変更できません。変えるには、ディレクトリを無効にして"
                "削除し、作り直してください（配下のユーザーとグループの対応表も削除されます）。"
            )
        if body.mappings is not None:
            # 古い行を先に消して確定させる（同じグループを残すと、追加が先に走って一意制約に反するため）
            config.mappings.clear()
            await db.flush()
            config.mappings = _mapping_rows(body.mappings)
        if disabling or identity_changed:
            # 無効にしたディレクトリのユーザーは、使用中のセッションも使えなくする。接続先や検索・グループの
            # 条件、対応表が変わったら、古い条件で認証・ロールを決めたセッションは使わせない（新しい条件では
            # ユーザーが見つからない・ロールが変わることがある）。次のログインで決め直す
            await _touch(db, config)
            await _revoke_directory_sessions(db, config.id)
        config.updated_at = utcnow()
        await _flush_checking_name(db)
        user_count = (await _user_counts(db)).get(config.id, 0)
        result = _to_read(config, user_count)
    _audit_saved(
        "directory_updated",
        principal,
        config,
        mappings_changed=body.mappings is not None,
        verified_by=verified.username if verified is not None else None,
    )
    return result


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


async def _run_test(
    principal: Principal,
    config: DirectoryConfig,
    settings: Settings,
    *,
    username: str | None,
    password: str | None,
    realm: str | None,
    unsaved: bool,
) -> DirectoryTestResponse:
    stages = await run_directory_call(
        run_test,
        spec_from_model(config),
        connect_options(settings),
        username=(username or None),
        password=(password or None),
    )
    audit(
        "directory_tested",
        actor=principal.username,
        directory=config.name,
        ok=all(s.ok for s in stages),
        realm=realm,
        unsaved=unsaved,
    )
    return DirectoryTestResponse(
        ok=all(s.ok for s in stages),
        stages=[DirectoryTestStage(stage=s.stage, ok=s.ok, message=s.message) for s in stages],
    )


@router.post("/test", response_model=DirectoryTestResponse)
async def test_unsaved_directory(
    body: DirectoryTestUnsavedRequest,
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_app_settings),
) -> DirectoryTestResponse:
    """まだ保存していない設定で接続を試す（DB には書かない）。"""
    config = _new_config(body)
    _validate(config, settings)
    return await _run_test(
        principal, config, settings, username=body.username, password=body.password, realm=None, unsaved=True
    )


@router.post("/{directory_id}/test", response_model=DirectoryTestResponse)
async def test_directory(
    directory_id: uuid.UUID,
    body: DirectoryTestRequest,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> DirectoryTestResponse:
    """保存済みの設定で接続を試す（無効のディレクトリでも試せる）。

    ``changes`` / ``mappings`` を渡すと、保存せずに重ねて試す（bind パスワードを送らなければ保存済みのものを
    使う）。DB には書かず、セッションも失効させない。
    """
    config = await _load(db, directory_id)
    unsaved = body.changes is not None or body.mappings is not None
    if unsaved:
        changes = body.changes.model_dump(exclude_unset=True, exclude={"clear_bind_password"}) if body.changes else {}
        config = _edited(
            config,
            changes,
            clear_bind_password=bool(body.changes and body.changes.clear_bind_password),
            mappings=body.mappings,
            settings=settings,
        )
    return await _run_test(
        principal,
        config,
        settings,
        username=body.username,
        password=body.password,
        realm=realm_key_for(directory_id),
        unsaved=unsaved,
    )
