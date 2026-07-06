"""手動インジェストエンドポイント。"""

from fastapi import APIRouter, Depends, HTTPException, status

from vcenter_event_assistant.api.deps import get_app_settings
from vcenter_event_assistant.services.ingest_runner import IngestBusyError, run_ingest_all
from vcenter_event_assistant.settings import Settings

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/run")
async def run_ingest_now(
    settings: Settings = Depends(get_app_settings),
) -> dict[str, str | int]:
    """全有効 vCenter のイベント・メトリクスを手動取り込みする。"""
    try:
        result = await run_ingest_all(settings)
    except IngestBusyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ingest already running",
        ) from None
    return {
        "status": "ok",
        "events_inserted": result.events_inserted,
        "metrics_inserted": result.metrics_inserted,
    }
