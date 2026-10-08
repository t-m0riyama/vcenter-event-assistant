"""FastAPI アプリケーションエントリ。

``create_app`` で API ルーター・CORS・静的 SPA フォールバックを組み立て、
lifespan で DB 初期化と APScheduler を管理する。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from vcenter_event_assistant.rate_limit import check_rate_limit

from vcenter_event_assistant.api.auth_deps import get_current_principal
from vcenter_event_assistant.api.routes.auth import router as auth_router
from vcenter_event_assistant.api.routes.auth_directories import (
    router as auth_directories_router,
)
from vcenter_event_assistant.api.routes.auth_users import router as auth_users_router
from vcenter_event_assistant.api.routes.chat import router as chat_router
from vcenter_event_assistant.api.routes.config import router as config_router
from vcenter_event_assistant.api.routes.dashboard import router as dashboard_router
from vcenter_event_assistant.api.routes.digests import router as digests_router
from vcenter_event_assistant.api.routes.event_score_rules import (
    router as event_score_rules_router,
)
from vcenter_event_assistant.api.routes.event_type_guides import (
    router as event_type_guides_router,
)
from vcenter_event_assistant.api.routes.events import router as events_router
from vcenter_event_assistant.api.routes.logs import router as logs_router
from vcenter_event_assistant.api.routes.health import router as health_router
from vcenter_event_assistant.api.routes.metrics import router as metrics_router
from vcenter_event_assistant.api.routes.vcenters import router as vcenters_router
from vcenter_event_assistant.api.routes.alerts import router as alerts_router
from vcenter_event_assistant.api.routes.ingest import router as ingest_router
from vcenter_event_assistant.api.routes.incident_timeline import (
    router as incident_timeline_router,
)
from vcenter_event_assistant.api.routes.plugins import (
    installed_router as plugins_installed_router,
    management_gate as plugins_management_gate,
    management_router as plugins_management_router,
    router as plugins_router,
)
from vcenter_event_assistant.auth.bootstrap import ensure_bootstrap_admin
from vcenter_event_assistant.auth.csrf import CsrfMiddleware
from vcenter_event_assistant.auth.principal_header import PrincipalHeaderMiddleware
from vcenter_event_assistant.dev.mock_mode_seed import run_mock_mode_seed_if_enabled
from vcenter_event_assistant.dev.screenshot_e2e_seed import (
    run_screenshot_e2e_seed_if_enabled,
)
from vcenter_event_assistant.db.session import init_db
from vcenter_event_assistant.db.vcenter_password_migration import (
    ensure_vcenter_password_storage,
)
from vcenter_event_assistant.jobs.scheduler import setup_scheduler, shutdown_scheduler
from vcenter_event_assistant.logging_config import configure_logging
from vcenter_event_assistant.services.digest.legacy_settings_deprecation import (
    warn_if_legacy_digest_settings_in_use,
)
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.settings_binding import bind_settings
from vcenter_event_assistant.security_startup import validate_startup_settings
from vcenter_event_assistant.plugins.registry import (
    get_collector_registry,
    set_collector_registry,
    shutdown_collector_registry,
)
from vcenter_event_assistant.plugins.reload import build_initial_collector_registry

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

_RATE_LIMITED_POST_PATHS: dict[str, tuple[str, int]] = {
    "/api/auth/login": ("login", 60),
    "/api/chat": ("chat", 60),
    "/api/chat/preview": ("chat_preview", 60),
    "/api/ingest/run": ("ingest", 60),
    "/api/digests/run": ("digests", 60),
    "/api/plugins/collectors/reload": ("plugins", 60),
    "/api/plugins/installed": ("plugins", 60),
    "/api/plugins/installed/upload": ("plugins", 60),
}


def is_spa_fallback_reserved_path(full_path: str) -> bool:
    """SPA フォールバックで配信してはいけないパス（API / OpenAPI）かどうか。"""
    return (
        full_path == "api"
        or full_path.startswith("api/")
        or full_path in ("docs", "openapi.json", "redoc")
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時に DB 初期化とスケジューラ開始、終了時に scheduler を停止する。"""
    settings = get_settings()
    warn_if_legacy_digest_settings_in_use(settings)
    if settings.is_production and settings.langsmith_tracing_enabled:
        logger.warning(
            "LangSmith tracing is enabled in production; LLM prompts may be sent to external services."
        )
    from vcenter_event_assistant.services.ssh_management import cleanup_stale_ssh_files

    cleanup_stale_ssh_files()
    await init_db(settings=settings)
    await ensure_bootstrap_admin(settings)
    await ensure_vcenter_password_storage(settings=settings)
    registry = await build_initial_collector_registry(settings)
    await run_screenshot_e2e_seed_if_enabled()
    await run_mock_mode_seed_if_enabled()
    if settings.scheduler_enabled:
        setup_scheduler(app, settings, registry=registry)
    yield
    shutdown_scheduler(app)
    # ホットリロード後は起動時のローカル変数が旧世代を指すため、現行スナップショットを引き直す。
    await shutdown_collector_registry(get_collector_registry())
    set_collector_registry(None)


def create_app() -> FastAPI:
    """設定に基づき FastAPI アプリを構築する。

    Returns:
        ルーター・ミドルウェア・（存在すれば）フロントエンド静的配信を設定したアプリ。
    """
    settings = get_settings()
    bind_settings(settings)
    validate_startup_settings(settings)
    configure_logging(settings)
    docs_enabled = settings.enable_openapi_docs and not settings.is_production
    app = FastAPI(
        title="vCenter Event Assistant",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if settings.is_production and ("*" in origins or not origins):
        origins = []
    allowed_origins = origins or ["http://localhost:5173"]
    # 認証は同一オリジン専用（SameSite=Strict の Cookie）。資格情報付き CORS は有効にしないので、
    # 別オリジンの UI からはログインできない。UI は同一オリジンかプロキシ経由で配信する前提。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        # X-VEA-Background: 画面の定期更新など、利用者の操作によらない要求の印（フロントの userActivity.ts）
        # X-VEA-Expected-Principal: 画面に表示中の利用者（フロントの api.ts。auth_deps で照合する）
        allow_headers=[
            "Accept",
            "Content-Type",
            "Authorization",
            "X-Requested-With",
            "X-VEA-Background",
            "X-VEA-Expected-Principal",
        ],
    )

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault(
                "Referrer-Policy", "strict-origin-when-cross-origin"
            )
            response.headers.setdefault(
                "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
            )
            if settings.is_production:
                response.headers.setdefault(
                    "Content-Security-Policy-Report-Only",
                    "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'",
                )
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if os.environ.get("VEA_PYTEST") == "1":
                return await call_next(request)
            if request.method == "POST":
                spec = _RATE_LIMITED_POST_PATHS.get(request.url.path)
                if spec is not None:
                    bucket, window = spec
                    client_host = request.client.host if request.client else "unknown"
                    key = f"{bucket}:{client_host}"
                    limit = {
                        "chat": settings.rate_limit_chat_per_minute,
                        "chat_preview": settings.rate_limit_chat_per_minute * 2,
                        "ingest": settings.rate_limit_ingest_per_minute,
                        "digests": settings.rate_limit_digests_per_minute,
                        "plugins": settings.rate_limit_plugins_per_minute,
                        "login": settings.rate_limit_login_per_minute,
                    }[bucket]
                    if not check_rate_limit(key, limit=limit, window_seconds=window):
                        return JSONResponse(
                            status_code=429,
                            content={"detail": "Too many requests"},
                        )
            return await call_next(request)

    app.add_middleware(RateLimitMiddleware)

    class NoStoreApiCacheMiddleware(BaseHTTPMiddleware):
        """動的 API の GET が中間キャッシュ・ブラウザに残らないよう ``Cache-Control: no-store`` を付与する。"""

        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            p = request.url.path
            if p == "/api" or p.startswith("/api/"):
                response.headers["Cache-Control"] = "no-store"
            return response

    app.add_middleware(NoStoreApiCacheMiddleware)

    if settings.auth_enabled:
        app.add_middleware(CsrfMiddleware, trusted_origins=allowed_origins)
        app.add_middleware(PrincipalHeaderMiddleware)

    app.include_router(health_router)

    app.include_router(auth_router)
    app.include_router(auth_users_router)
    app.include_router(auth_directories_router)

    # ``/api`` 配下は全 route でログインを必須にし、各 route が最低ロールを宣言する。
    api = APIRouter(prefix="/api", dependencies=[Depends(get_current_principal)])
    api.include_router(config_router)
    api.include_router(event_score_rules_router)
    api.include_router(event_type_guides_router)
    api.include_router(vcenters_router)
    api.include_router(events_router)
    api.include_router(logs_router)
    api.include_router(metrics_router)
    api.include_router(dashboard_router)
    api.include_router(digests_router)
    api.include_router(chat_router)
    api.include_router(incident_timeline_router)
    api.include_router(alerts_router)
    api.include_router(ingest_router)
    api.include_router(plugins_router)

    app.include_router(api)

    # プラグイン管理の変更系は、無効時に存在を伏せる 404 gate をログイン確認より先に評価する。
    # 親 router の依存は子より先に走るため、``api`` には入れずにここで順序を指定してマウントする。
    from vcenter_event_assistant.api.routes.plugin_setup import (
        router as plugin_setup_router,
    )

    for gated in (
        plugins_management_router,
        plugins_installed_router,
        plugin_setup_router,
    ):
        app.include_router(
            gated,
            prefix="/api",
            dependencies=[
                Depends(plugins_management_gate),
                Depends(get_current_principal),
            ],
        )

    if FRONTEND_DIST.is_dir() and (FRONTEND_DIST / "index.html").is_file():
        assets = FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if is_spa_fallback_reserved_path(full_path):
                raise HTTPException(status_code=404, detail="Not found")

            target_path = (FRONTEND_DIST / full_path).resolve()
            try:
                if (
                    target_path.is_relative_to(FRONTEND_DIST.resolve())
                    and target_path.is_file()
                ):
                    return FileResponse(target_path)
            except ValueError:
                pass  # Fallback to index.html if resolution fails or is not relative

            return FileResponse(FRONTEND_DIST / "index.html")

    return app
