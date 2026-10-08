"""Pytest fixtures."""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Settings の `.env` 読み込みを無効化（`src/.../settings.py` の `_settings_env_file` 参照）
os.environ["VEA_PYTEST"] = "1"

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SCHEDULER_ENABLED"] = "false"
# 開発者の .env に LLM キーがあっても、テストで外部 API を呼ばない
os.environ["LLM_DIGEST_API_KEY"] = ""
# .env の APP_LOG_FILE へ書かない（digest_llm の失敗系テストの WARNING が混ざるのを防ぐ）
os.environ["APP_LOG_FILE"] = ""
os.environ["VEA_ALLOW_PLAINTEXT_PASSWORDS"] = "1"
# 認証を有効にした状態でテストする。``client`` は admin でログイン済み（``open_client`` 参照）。
os.environ["VEA_AUTH_ENABLED"] = "1"
# CI 等で openaipublic.blob.core.windows.net へ届かない環境でも cl100k_base を使えるよう
# リポジトリ同梱キャッシュを優先する（未設定時のみ。開発者が独自キャッシュを使う場合は上書き可）
os.environ.setdefault(
    "TIKTOKEN_CACHE_DIR",
    str(Path(__file__).resolve().parent / "fixtures" / "tiktoken_cache"),
)

from vcenter_event_assistant.api.auth_deps import session_cookie_name
from vcenter_event_assistant.auth.service import session_policy
from vcenter_event_assistant.auth.sessions import create_session
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.db.models import User
from vcenter_event_assistant.db.session import get_engine, init_db, reset_db, session_scope
from vcenter_event_assistant.db.startup_migration import run_startup_migration
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.settings import Settings, get_settings
from vcenter_event_assistant.settings_binding import bind_settings, clear_settings_binding

get_settings.cache_clear()
bind_settings(get_settings())


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--test-db-setup",
        choices=("template", "migrate"),
        default="template",
        help="Prepare each application test DB from a migrated template or run migrations.",
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Each pytest worker owns a fresh, fully migrated database for this run."""
    path = tmp_path_factory.mktemp("db-template") / "empty.db"
    settings = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{path}")
    engine = create_async_engine(settings.database_url)
    try:
        await run_startup_migration(engine, settings=settings)
    finally:
        await engine.dispose()
    return path


@pytest.fixture
def load_db_template(db_template: Path) -> Callable[[AsyncEngine], Awaitable[None]]:
    async def load(engine: AsyncEngine) -> None:
        async with engine.connect() as connection:
            raw = await connection.get_raw_connection()
            async with aiosqlite.connect(
                f"{db_template.as_uri()}?mode=ro", uri=True
            ) as source:
                await source.backup(raw.driver_connection)

    return load


def _fake_vcenter_getaddrinfo(
    host: str,
    port: object,
    family: int = 0,
    type: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> list[tuple]:
    """vCenter テスト用: ホスト名を公開 IP に解決した扱いにする（SSRF DNS 検証用）。"""
    _ = (host, port, family, type, proto, flags)
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


@pytest.fixture(autouse=True)
def _mock_vcenter_host_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vcenter_event_assistant.services.vcenter_host_validation.socket.getaddrinfo",
        _fake_vcenter_getaddrinfo,
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """`test_digest*` / `test_digests_api*` を高負荷マーカーに付与（既定の addopts で除外）。

    `test_digest_llm.py` / `test_digest_status.py` は HTTP モックまたは純粋ユニットのため `digest_heavy` に含めない。
    """
    for item in items:
        name = Path(str(item.path)).name
        if name in ("test_digest_llm.py", "test_digest_status.py"):
            continue
        if name.startswith("test_digest") or name == "test_digests_api.py":
            item.add_marker(pytest.mark.digest_heavy)


@pytest.fixture(autouse=True)
async def _db_setup(
    request: pytest.FixtureRequest,
    load_db_template: Callable[[AsyncEngine], Awaitable[None]],
) -> None:
    await reset_db()
    get_settings.cache_clear()
    settings = get_settings()
    bind_settings(settings)
    try:
        engine = get_engine(settings=settings)
        if (
            request.config.getoption("--test-db-setup") == "migrate"
            or request.node.get_closest_marker("real_db_init") is not None
            or engine.url.get_backend_name() != "sqlite"
            or engine.url.database != ":memory:"
        ):
            await init_db(settings=settings)
        else:
            await load_db_template(engine)
        yield
    finally:
        await reset_db()
        get_settings.cache_clear()
        clear_settings_binding()


@pytest.fixture
def no_external_collectors(monkeypatch: pytest.MonkeyPatch) -> None:
    """entry point の走査を空にして、組み込みコレクタだけのレジストリにする。

    開発 venv に外部プラグインが入っていると、レジストリの件数を見るテストが
    環境依存で落ちる。プラグイン検出そのものを試すテストでは使わない。
    """
    monkeypatch.setattr(
        "vcenter_event_assistant.plugins.registry.entry_points", lambda **_: []
    )


async def login_cookie(role: str, *, username: str | None = None) -> tuple[str, str]:
    """``role`` のローカルユーザーとセッションを直接作り、(Cookie 名, トークン) を返す。

    argon2 を通さないため速い（password_hash は空で、パスワードログインはできない）。
    """
    settings = get_settings()
    name = username or f"test-{role}"
    now = utcnow()
    async with session_scope(settings) as db:
        user = User(
            realm_key="local",
            subject=name.casefold(),
            username=name,
            role=role,
            is_active=True,
            failed_login_count=0,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        await db.flush()
        token = await create_session(db, user, session_policy(settings))
    return session_cookie_name(settings), token


@pytest.fixture
def open_client():
    """``async with open_client(role="viewer") as c:`` で任意ロールのクライアントを開く。

    ``role=None`` は未ログイン。``app`` を渡すとそのアプリを使う（既定は ``create_app()``）。
    変更系リクエストに必要な ``X-Requested-With`` は既定ヘッダとして付ける。
    """

    @asynccontextmanager
    async def _open(role: str | None = "admin", *, app=None, username: str | None = None) -> AsyncIterator[AsyncClient]:
        target = app if app is not None else create_app()
        cookies = {}
        if role is not None:
            name, token = await login_cookie(role, username=username)
            cookies[name] = token
        async with AsyncClient(
            transport=ASGITransport(app=target),
            base_url="http://test",
            headers={"X-Requested-With": "XMLHttpRequest"},
            cookies=cookies,
        ) as ac:
            yield ac

    return _open


@pytest.fixture
async def client(open_client) -> AsyncIterator[AsyncClient]:
    async with open_client("admin") as ac:
        yield ac


@pytest.fixture
async def anon_client(open_client) -> AsyncIterator[AsyncClient]:
    async with open_client(None) as ac:
        yield ac


@pytest.fixture
async def viewer_client(open_client) -> AsyncIterator[AsyncClient]:
    async with open_client("viewer") as ac:
        yield ac


@pytest.fixture
async def operator_client(open_client) -> AsyncIterator[AsyncClient]:
    async with open_client("operator") as ac:
        yield ac
