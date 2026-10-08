"""初期 admin の作成と、子プロセスへの秘密の受け渡し防止。

期限切れセッションの定期削除は tests/test_auth_api.py で確認している。
"""

from __future__ import annotations


import pytest

from vcenter_event_assistant.auth.bootstrap import BootstrapError, ensure_bootstrap_admin
from vcenter_event_assistant.auth.passwords import verify_password
from vcenter_event_assistant.auth.users import count_users, create_local_user, get_local_user
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins.subprocess_env import child_process_env
from vcenter_event_assistant.settings import get_settings

BOOT_PASSWORD = "bootstrap long password"


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings()


async def test_creates_admin_once(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        monkeypatch,
        VEA_BOOTSTRAP_ADMIN_USERNAME="root",
        VEA_BOOTSTRAP_ADMIN_PASSWORD=BOOT_PASSWORD,
    )
    await ensure_bootstrap_admin(settings)
    await ensure_bootstrap_admin(settings)
    async with session_scope() as db:
        assert await count_users(db) == 1
        user = await get_local_user(db, "root")
        assert user is not None and user.role == "admin"
        assert (await verify_password(user.password_hash, BOOT_PASSWORD)).ok


async def test_does_not_override_existing_users(monkeypatch: pytest.MonkeyPatch) -> None:
    async with session_scope() as db:
        await create_local_user(
            db, username="existing", password="existing long pw", role="viewer", password_min_length=12
        )
    settings = _settings(
        monkeypatch,
        VEA_BOOTSTRAP_ADMIN_USERNAME="root",
        VEA_BOOTSTRAP_ADMIN_PASSWORD=BOOT_PASSWORD,
    )
    await ensure_bootstrap_admin(settings)
    async with session_scope() as db:
        assert await get_local_user(db, "root") is None


@pytest.mark.parametrize(
    "env",
    [
        {"VEA_BOOTSTRAP_ADMIN_USERNAME": "root", "VEA_BOOTSTRAP_ADMIN_PASSWORD": "short"},
        {"VEA_BOOTSTRAP_ADMIN_USERNAME": "root"},
        {"VEA_BOOTSTRAP_ADMIN_PASSWORD": BOOT_PASSWORD},
    ],
)
async def test_invalid_bootstrap_config_stops_startup(monkeypatch: pytest.MonkeyPatch, env) -> None:
    with pytest.raises(BootstrapError):
        await ensure_bootstrap_admin(_settings(monkeypatch, **env))


async def test_no_users_without_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    # 開発環境では警告だけ
    await ensure_bootstrap_admin(_settings(monkeypatch))
    # 本番で認証が有効なら起動を止める
    prod = _settings(
        monkeypatch,
        APP_ENV="production",
        VEA_SECRET_KEY="prod-secret-key",
        VCENTER_ALLOWED_HOST_SUFFIXES="example.com",
    )
    with pytest.raises(BootstrapError, match="--role admin"):
        await ensure_bootstrap_admin(prod)
    # 認証が無効なら何もしない
    await ensure_bootstrap_admin(_settings(monkeypatch, VEA_AUTH_ENABLED="false"))


async def test_users_without_active_admin_are_reported(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """CLI の create-user を既定ロールで実行しただけの状態（admin 不在）も検出する。"""
    async with session_scope() as db:
        await create_local_user(
            db, username="only-viewer", password="viewer long pw", role="viewer", password_min_length=12
        )
    caplog.set_level("WARNING", logger="vcenter_event_assistant.auth.bootstrap")
    await ensure_bootstrap_admin(_settings(monkeypatch))
    assert "--role admin" in caplog.text and "set-role" in caplog.text

    prod = _settings(
        monkeypatch,
        APP_ENV="production",
        VEA_SECRET_KEY="prod-secret-key",
        VCENTER_ALLOWED_HOST_SUFFIXES="example.com",
    )
    with pytest.raises(BootstrapError, match="--role admin"):
        await ensure_bootstrap_admin(prod)
    await ensure_bootstrap_admin(_settings(monkeypatch, VEA_AUTH_ENABLED="false"))


async def test_bootstrap_rejected_when_local_login_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """ローカルログインが無効だと初期 admin でログインできないため、作らずに起動を止める。"""
    settings = _settings(
        monkeypatch,
        VEA_LOCAL_LOGIN_ENABLED="false",
        VEA_BOOTSTRAP_ADMIN_USERNAME="root",
        VEA_BOOTSTRAP_ADMIN_PASSWORD=BOOT_PASSWORD,
    )
    with pytest.raises(BootstrapError, match="VEA_LOCAL_LOGIN_ENABLED"):
        await ensure_bootstrap_admin(settings)
    async with session_scope() as db:
        assert await count_users(db) == 0


@pytest.mark.parametrize("local_login", ["true", "false"])
@pytest.mark.parametrize(
    "env",
    [
        {"VEA_BOOTSTRAP_ADMIN_USERNAME": "root", "VEA_BOOTSTRAP_ADMIN_PASSWORD": BOOT_PASSWORD},
        {"VEA_BOOTSTRAP_ADMIN_USERNAME": "root", "VEA_BOOTSTRAP_ADMIN_PASSWORD": "short"},
        {"VEA_BOOTSTRAP_ADMIN_USERNAME": "root"},
        {"VEA_BOOTSTRAP_ADMIN_PASSWORD": BOOT_PASSWORD},
    ],
)
async def test_bootstrap_settings_are_ignored_when_auth_disabled(
    monkeypatch: pytest.MonkeyPatch, local_login: str, env: dict[str, str]
) -> None:
    """認証が無効なら、初期 admin の設定が残っていても起動を止めず、アカウントも作らない。"""
    settings = _settings(
        monkeypatch, VEA_AUTH_ENABLED="false", VEA_LOCAL_LOGIN_ENABLED=local_login, **env
    )
    await ensure_bootstrap_admin(settings)
    async with session_scope() as db:
        assert await count_users(db) == 0


async def test_no_usable_realm_is_reported(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """ローカルの admin がいても、ローカルログインが無効なら誰もログインできない。"""
    async with session_scope() as db:
        await create_local_user(
            db, username="admin1", password="admin1 long pw", role="admin", password_min_length=12
        )
    caplog.set_level("WARNING", logger="vcenter_event_assistant.auth.bootstrap")
    await ensure_bootstrap_admin(_settings(monkeypatch, VEA_LOCAL_LOGIN_ENABLED="false"))
    assert "ログインできる認証先がありません" in caplog.text

    prod = _settings(
        monkeypatch,
        APP_ENV="production",
        VEA_SECRET_KEY="prod-secret-key",
        VCENTER_ALLOWED_HOST_SUFFIXES="example.com",
    )
    with pytest.raises(BootstrapError, match="ログインできる認証先"):
        await ensure_bootstrap_admin(prod)
    # 認証が無効なら何もしない
    await ensure_bootstrap_admin(_settings(monkeypatch, VEA_AUTH_ENABLED="false"))


async def test_concurrent_duplicate_that_is_not_admin_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """同名ユーザーが先に viewer として作られていたら、admin 作成済みとはみなさない。"""
    async with session_scope() as db:
        await create_local_user(
            db, username="root", password="viewer long pw", role="viewer", password_min_length=12
        )

    async def zero(db):
        return 0

    async def not_found(db, username):
        return None

    # 自分の確認時点ではユーザー 0 人に見えていた（その直後に他方が作った）状況を再現する
    monkeypatch.setattr("vcenter_event_assistant.auth.bootstrap.count_users", zero)
    monkeypatch.setattr("vcenter_event_assistant.auth.users.get_local_user", not_found)
    prod = _settings(
        monkeypatch,
        APP_ENV="production",
        VEA_SECRET_KEY="prod-secret-key",
        VCENTER_ALLOWED_HOST_SUFFIXES="example.com",
        VEA_BOOTSTRAP_ADMIN_USERNAME="root",
        VEA_BOOTSTRAP_ADMIN_PASSWORD=BOOT_PASSWORD,
    )
    with pytest.raises(BootstrapError, match="有効な admin がいません"):
        await ensure_bootstrap_admin(prod)


@pytest.mark.parametrize(
    "name",
    [
        "VEA_BOOTSTRAP_ADMIN_PASSWORD",
        "vea_bootstrap_admin_password",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "bootstrap_admin_password",
    ],
)
def test_child_process_env_withholds_bootstrap_password(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    # Settings が受け付ける綴りはすべて除外する
    monkeypatch.setenv(name, "secret")
    monkeypatch.setenv("SOME_OTHER_VAR", "kept")
    get_settings.cache_clear()
    assert get_settings().bootstrap_admin_password is not None
    env = child_process_env()
    assert "secret" not in env.values()
    assert env["SOME_OTHER_VAR"] == "kept"


async def test_concurrent_bootstrap_by_another_process_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """別プロセスが先に初期 admin を作っていても（一意制約違反）、起動は止めない。"""
    settings = _settings(
        monkeypatch,
        VEA_BOOTSTRAP_ADMIN_USERNAME="root",
        VEA_BOOTSTRAP_ADMIN_PASSWORD=BOOT_PASSWORD,
    )
    await ensure_bootstrap_admin(settings)

    async def zero(db):
        return 0

    async def not_found(db, username):
        return None

    monkeypatch.setattr("vcenter_event_assistant.auth.bootstrap.count_users", zero)
    monkeypatch.setattr("vcenter_event_assistant.auth.users.get_local_user", not_found)
    await ensure_bootstrap_admin(settings)


async def _add_directory(*, enabled: bool, role: str) -> None:
    from vcenter_event_assistant.auth.directory.role_mapping import normalize_dn
    from vcenter_event_assistant.db.models import DirectoryConfig, DirectoryGroupRoleMapping

    group = "cn=Admins,dc=example,dc=com"
    async with session_scope() as db:
        db.add(
            DirectoryConfig(
                name="corp",
                kind="ad",
                is_enabled=enabled,
                server_uris=["ldaps://dc.example.com"],
                transport_security="ldaps",
                user_search_base="dc=example,dc=com",
                group_mode="ad_nested",
                mappings=[
                    DirectoryGroupRoleMapping(group_dn=group, group_dn_normalized=normalize_dn(group), role=role)
                ],
            )
        )


@pytest.mark.parametrize("local_login", ["true", "false"])
async def test_directory_admin_mapping_counts_as_a_way_to_administer(
    monkeypatch: pytest.MonkeyPatch, local_login: str
) -> None:
    """ディレクトリ専用の運用では admin の行は初回ログインまでないので、admin の対応があれば起動を止めない。"""
    await _add_directory(enabled=True, role="admin")
    prod = _settings(
        monkeypatch,
        APP_ENV="production",
        VEA_SECRET_KEY="prod-secret-key",
        VCENTER_ALLOWED_HOST_SUFFIXES="example.com",
        VEA_LOCAL_LOGIN_ENABLED=local_login,
    )
    await ensure_bootstrap_admin(prod)
    async with session_scope() as db:
        assert await count_users(db) == 0


@pytest.mark.parametrize(("enabled", "role"), [(False, "admin"), (True, "operator")])
async def test_directory_without_admin_does_not_count(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, role: str
) -> None:
    await _add_directory(enabled=enabled, role=role)
    prod = _settings(
        monkeypatch,
        APP_ENV="production",
        VEA_SECRET_KEY="prod-secret-key",
        VCENTER_ALLOWED_HOST_SUFFIXES="example.com",
        VEA_LOCAL_LOGIN_ENABLED="false",
    )
    with pytest.raises(BootstrapError, match="ログインできる認証先"):
        await ensure_bootstrap_admin(prod)
