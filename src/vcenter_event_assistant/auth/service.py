"""ログイン処理の入口。realm ごとの認証バックエンドへ振り分ける。"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from vcenter_event_assistant.auth.audit import audit
from vcenter_event_assistant.auth.directory import backend as directory_backend
from vcenter_event_assistant.auth.directory.backend import DirectoryIdentity
from vcenter_event_assistant.auth.directory.connection import allowed_by_security
from vcenter_event_assistant.auth.directory.errors import DirectoryError
from vcenter_event_assistant.auth.directory.runner import connect_options, run_directory_call
from vcenter_event_assistant.auth.directory.spec import spec_from_model
from vcenter_event_assistant.auth.passwords import (
    PASSWORD_MAX_LENGTH,
    hash_password,
    verify_password,
)
from vcenter_event_assistant.auth.sessions import SessionPolicy, credential_marker
from vcenter_event_assistant.auth.timeutil import as_utc, utcnow
from vcenter_event_assistant.auth.users import (
    DISPLAY_NAME_MAX_LENGTH,
    EMAIL_MAX_LENGTH,
    LOCAL_REALM,
    SUBJECT_MAX_LENGTH,
    USERNAME_MAX_LENGTH,
    UserError,
    get_local_user,
    normalize_username,
)
from vcenter_event_assistant.db.models import DirectoryConfig, User
from vcenter_event_assistant.settings import Settings

# 失敗理由（ユーザー不在・パスワード誤り・ロック中・無効化）を画面に出し分けない。
GENERIC_LOGIN_ERROR = "ユーザー名またはパスワードが正しくありません。"


@dataclass(frozen=True)
class Realm:
    id: str
    name: str
    kind: str


@dataclass(frozen=True)
class LoginOutcome:
    user: User | None
    reason: str

    @property
    def ok(self) -> bool:
        return self.user is not None


def session_policy(settings: Settings) -> SessionPolicy:
    return SessionPolicy(
        idle_timeout=timedelta(minutes=settings.session_idle_timeout_minutes),
        absolute_timeout=timedelta(hours=settings.session_absolute_timeout_hours),
        directory_options=connect_options(settings),
    )


DIRECTORY_REALM_PREFIX = "dir:"
logger = logging.getLogger(__name__)


async def list_realms(db: AsyncSession, settings: Settings) -> list[Realm]:
    """ログイン画面に出す認証先（ローカルと、有効で今の接続の方針で拒否されないディレクトリ）。"""
    realms: list[Realm] = []
    if settings.local_login_enabled:
        realms.append(Realm(id=LOCAL_REALM, name="ローカル", kind="local"))
    directories = await db.scalars(
        select(DirectoryConfig)
        .where(DirectoryConfig.is_enabled.is_(True), allowed_by_security(connect_options(settings)))
        .order_by(DirectoryConfig.sort_order, DirectoryConfig.name)
    )
    for d in directories:
        realms.append(Realm(id=f"{DIRECTORY_REALM_PREFIX}{d.id}", name=d.name, kind=d.kind))
    return realms


async def _load_directory(db: AsyncSession, realm: str) -> DirectoryConfig | None:
    """realm（``dir:<uuid>``）に対応する有効なディレクトリ。"""
    try:
        directory_id = uuid.UUID(realm.removeprefix(DIRECTORY_REALM_PREFIX))
    except ValueError:
        return None
    return await db.scalar(
        select(DirectoryConfig)
        .where(DirectoryConfig.id == directory_id, DirectoryConfig.is_enabled.is_(True))
        .options(selectinload(DirectoryConfig.mappings))
    )


def _subject_key(subject: str) -> str:
    """``users.subject`` に入れる値。長すぎる識別子（長い DN など）は切り詰めずにハッシュにする。

    切り詰めると、先頭が同じ別の DN が同じユーザー行になってしまうため。
    """
    if len(subject) <= SUBJECT_MAX_LENGTH:
        return subject
    return f"sha256:{hashlib.sha256(subject.encode('utf-8')).hexdigest()}"


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value[:limit] or None


async def _upsert_directory_user(
    db: AsyncSession, config: DirectoryConfig, identity: DirectoryIdentity, now: datetime
) -> User | None:
    """ディレクトリのユーザーの行を作るか更新する（ロールはログインのたびに対応表から決め直す）。

    無効化されたユーザーなら ``None``（呼び出し側がセーブポイントを巻き戻して、更新も取り消す）。
    """
    realm_key = f"{DIRECTORY_REALM_PREFIX}{config.id}"
    subject = _subject_key(identity.subject)
    values = {
        "username": identity.username[:USERNAME_MAX_LENGTH],
        "display_name": _clip(identity.display_name, DISPLAY_NAME_MAX_LENGTH),
        "email": _clip(identity.email, EMAIL_MAX_LENGTH),
        "role": identity.role.value,
        "directory_id": config.id,
        "last_login_at": now,
        "updated_at": now,
    }
    for _attempt in range(2):
        user = await db.scalar(
            select(User)
            .where(User.realm_key == realm_key, User.subject == subject)
            .execution_options(populate_existing=True)
        )
        if user is not None:
            if not user.is_active:
                return None
            for key, value in values.items():
                setattr(user, key, value)
            await db.flush()
            # 読んでから更新するまでの間に無効化されていないか、更新の後で読み直す。
            # 更新は変更した列だけを書くので行は無効のまま残るが、ログインを通すと使えない Cookie を返してしまう。
            # 更新で行ロックを取った後に読むので、無効化が先に確定していれば必ず見える（後なら無効化側が待ち、
            # このログインのセッションも失効させる）
            if not await db.scalar(select(User.is_active).where(User.id == user.id)):
                return None
            return user
        user = User(realm_key=realm_key, subject=subject, is_active=True, failed_login_count=0, **values)
        try:
            async with db.begin_nested():
                db.add(user)
        except IntegrityError:
            # 同じユーザーの初回ログインが並行して行を作った。読み直して更新する
            continue
        return user
    return None


class _DirectoryRecheckFailed(Exception):
    """認証後の再確認で拒否する（セーブポイントを巻き戻すために使う）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _authenticate_directory(
    db: AsyncSession, settings: Settings, realm: str, username: str, password: str
) -> LoginOutcome:
    config = await _load_directory(db, realm)
    if config is None:
        return LoginOutcome(None, "unknown_realm")
    spec = spec_from_model(config)
    config_version = config.updated_at
    try:
        identity = await run_directory_call(
            directory_backend.authenticate, spec, username, password, connect_options(settings)
        )
    except DirectoryError as exc:
        if exc.reason.startswith("directory_"):
            # 接続・設定の問題はユーザーの誤りではないので、運用者が気づけるようにログに残す
            logger.warning("Directory %r is unavailable: %s", config.name, exc)
        return LoginOutcome(None, exc.reason)
    except Exception:
        logger.exception("Unexpected error while authenticating against directory %r", config.name)
        return LoginOutcome(None, "directory_error")
    # 認証している間に無効化・変更（対応表の置き換えなど）されていたら、ログインさせない。
    # 変更時にセッションを失効させた後で、古い設定で決めたロールのセッションを作らないため。
    # 行をロックしておき、この後の変更はこのログインの確定を待ってから失効させるようにする。
    # ロックの順序は管理側（admin のユーザー行 → ディレクトリの行）と同じにする（逆順はデッドロックになる）ので、
    # ユーザー行を更新してからディレクトリの行をロックし、拒否するときはユーザー行の更新も取り消す
    try:
        async with db.begin_nested():
            user = await _upsert_directory_user(db, config, identity, utcnow())
            if user is None:
                raise _DirectoryRecheckFailed("inactive")
            current = (
                await db.execute(
                    select(DirectoryConfig.is_enabled, DirectoryConfig.updated_at)
                    .where(DirectoryConfig.id == config.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            if current is None or not current.is_enabled:
                raise _DirectoryRecheckFailed("directory_disabled")
            if current.updated_at != config_version:
                raise _DirectoryRecheckFailed("directory_changed")
    except _DirectoryRecheckFailed as exc:
        return LoginOutcome(None, exc.reason)
    return LoginOutcome(user, "ok")


async def _authenticate_local(
    db: AsyncSession, settings: Settings, username: str, password: str
) -> LoginOutcome:
    try:
        name = normalize_username(username)
    except UserError:
        await verify_password(None, password)
        return LoginOutcome(None, "invalid_username")
    user = await get_local_user(db, name)
    if user is None:
        await verify_password(None, password)
        return LoginOutcome(None, "unknown_user")

    now = utcnow()
    if user.locked_until is not None and as_utc(user.locked_until) > now:
        await verify_password(None, password)
        return LoginOutcome(None, "locked")

    generation = credential_marker(user)
    result = await verify_password(user.password_hash, password)
    if not result.ok:
        if await _record_failure(db, settings, user.id, now):
            audit("login_lockout", level=logging.WARNING, realm=LOCAL_REALM, username=user.username)
        return LoginOutcome(None, "bad_password")

    if not user.is_active:
        return LoginOutcome(None, "inactive")

    # refresh() は検証中に削除された行で例外になるため、無ければ None になる SELECT で読み直す
    fresh = await db.scalar(
        select(User).where(User.id == user.id).execution_options(populate_existing=True)
    )
    if fresh is None:
        return LoginOutcome(None, "user_deleted")
    user = fresh
    if credential_marker(user) != generation or not user.is_active:
        # 検証している間にパスワード変更・無効化が確定した。これより後の変更は
        # セッションの世代照合（sessions.credential_marker）で無効になる。
        return LoginOutcome(None, "credential_changed")
    if not await _record_success(db, user.id, now):
        # 検証している間に、並行した失敗でロックされた
        return LoginOutcome(None, "locked")
    if result.needs_rehash and user.password_hash is not None:
        await _rehash(db, user, password)
    return LoginOutcome(user, "ok")


# 失敗回数は読み込み済みの値から加算せず、DB 上で原子的に更新する。
# 並行した失敗が互いの加算を上書きすると、複数 IP からの試行でロックアウトを回避できるため。
_NO_SYNC = {"synchronize_session": False}


async def _record_failure(
    db: AsyncSession, settings: Settings, user_id: uuid.UUID, now: datetime
) -> bool:
    """失敗回数を 1 増やし、閾値に達したらロックする。ロックしたら ``True``。"""
    count = await db.scalar(
        update(User)
        .where(User.id == user_id)
        .values(failed_login_count=User.failed_login_count + 1)
        .returning(User.failed_login_count)
        .execution_options(**_NO_SYNC)
    )
    if count is None or count < settings.login_max_failed_attempts:
        return False
    locked = await db.execute(
        update(User)
        .where(User.id == user_id, User.failed_login_count >= settings.login_max_failed_attempts)
        .values(
            locked_until=now + timedelta(minutes=settings.login_lockout_minutes),
            failed_login_count=0,
        )
        .execution_options(**_NO_SYNC)
    )
    return bool(locked.rowcount)


async def _rehash(db: AsyncSession, user: User, password: str) -> None:
    """パラメータが古いハッシュを作り直す。

    検証したハッシュがまだ現在のものであるときだけ書き込む。ハッシュ計算中に確定した
    パスワード変更を、検証済みの古いパスワードで上書きしないため。
    """
    verified_hash = user.password_hash
    new_hash = await hash_password(password)
    done = await db.execute(
        update(User)
        .where(User.id == user.id, User.password_hash == verified_hash)
        .values(password_hash=new_hash)
        .execution_options(**_NO_SYNC)
    )
    if done.rowcount:
        set_committed_value(user, "password_hash", new_hash)


async def _record_success(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> bool:
    """ロックされていなければ失敗回数を戻して ``True``。ロック中なら ``False``。"""
    done = await db.execute(
        update(User)
        .where(
            User.id == user_id,
            or_(User.locked_until.is_(None), User.locked_until <= now),
        )
        .values(failed_login_count=0, locked_until=None, last_login_at=now)
        .execution_options(**_NO_SYNC)
    )
    return bool(done.rowcount)


async def authenticate(
    db: AsyncSession,
    settings: Settings,
    *,
    realm: str,
    username: str,
    password: str,
    client_ip: str | None,
) -> LoginOutcome:
    """認証して ``LoginOutcome`` を返す。成否はすべて監査ログに残す。"""
    if not password or len(password) > PASSWORD_MAX_LENGTH * 4:
        # 空パスワードは LDAP の unauthenticated bind で成功扱いになり得るため常に拒否する
        outcome = LoginOutcome(None, "empty_password" if not password else "too_long")
    elif realm == LOCAL_REALM and settings.local_login_enabled:
        outcome = await _authenticate_local(db, settings, username, password)
    elif realm.startswith(DIRECTORY_REALM_PREFIX):
        outcome = await _authenticate_directory(db, settings, realm, username, password)
    else:
        await verify_password(None, password)
        outcome = LoginOutcome(None, "unknown_realm")

    if outcome.ok:
        assert outcome.user is not None
        audit("login_success", realm=realm, username=outcome.user.username, role=outcome.user.role, ip=client_ip)
    else:
        audit(
            "login_failure",
            level=logging.WARNING,
            realm=realm,
            username=username[:256],
            reason=outcome.reason,
            ip=client_ip,
        )
    return outcome
