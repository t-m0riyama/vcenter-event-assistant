"""手動インジェストエンドポイント。"""

from fastapi import APIRouter
from sqlalchemy import select

from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.ingestion import (
    ingest_events_for_vcenter,
    ingest_metrics_for_vcenter,
    list_enabled_vcenters,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])

@router.post("/run")
async def run_ingest_now() -> dict[str, str | int]:
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
