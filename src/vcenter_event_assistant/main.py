"""FastAPI application entry."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from vcenter_event_assistant.api.routes.dashboard import router as dashboard_router
from vcenter_event_assistant.api.routes.events import router as events_router
from vcenter_event_assistant.api.routes.health import router as health_router
from vcenter_event_assistant.api.routes.metrics import router as metrics_router
from vcenter_event_assistant.api.routes.vcenters import router as vcenters_router
from vcenter_event_assistant.auth.dependencies import require_auth
from vcenter_event_assistant.db.session import init_db
from vcenter_event_assistant.jobs.scheduler import setup_scheduler, shutdown_scheduler
from vcenter_event_assistant.settings import get_settings

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    await init_db()
    settings = get_settings()
    if settings.scheduler_enabled:
        setup_scheduler(app)
    yield
    shutdown_scheduler(app)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="vCenter Event Assistant", lifespan=lifespan)

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)

    api = APIRouter(prefix="/api")
    api.include_router(vcenters_router)
    api.include_router(events_router)
    api.include_router(metrics_router)
    api.include_router(dashboard_router)

    @api.post("/ingest/run")
    async def run_ingest_now(_: None = Depends(require_auth)) -> dict[str, str | int]:
        from sqlalchemy import select

        from vcenter_event_assistant.db.models import VCenter
        from vcenter_event_assistant.db.session import session_scope
        from vcenter_event_assistant.services.ingestion import (
            ingest_events_for_vcenter,
            ingest_metrics_for_vcenter,
            list_enabled_vcenters,
        )

        async with session_scope() as session:
            vcenters = await list_enabled_vcenters(session)
            ids = [v.id for v in vcenters]
        ev_total = 0
        m_total = 0
        for vid in ids:
            async with session_scope() as session:
                res = await session.execute(select(VCenter).where(VCenter.id == vid))
                vc = res.scalar_one()
                ev_total += await ingest_events_for_vcenter(session, vc)
            async with session_scope() as session:
                res = await session.execute(select(VCenter).where(VCenter.id == vid))
                vc = res.scalar_one()
                m_total += await ingest_metrics_for_vcenter(session, vc)
        return {"status": "ok", "events_inserted": ev_total, "metrics_inserted": m_total}

    app.include_router(api)

    if FRONTEND_DIST.is_dir() and (FRONTEND_DIST / "index.html").is_file():
        assets = FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if full_path.startswith("api") or full_path in ("docs", "openapi.json", "redoc"):
                raise HTTPException(status_code=404, detail="Not found")
            return FileResponse(FRONTEND_DIST / "index.html")

    return app
