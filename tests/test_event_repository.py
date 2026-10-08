import pytest
from datetime import datetime, timezone
from vcenter_event_assistant.services.event_repository import get_event_rate_series
from vcenter_event_assistant.db.session import session_scope

@pytest.mark.asyncio
async def test_get_event_rate_series_empty():
    from_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    to_time = datetime(2026, 1, 2, tzinfo=timezone.utc)
    
    async with session_scope() as session:
        buckets = await get_event_rate_series(
            session=session,
            event_type="VmPoweredOnEvent",
            from_time=from_time,
            to_time=to_time,
            bucket_seconds=3600
        )
    assert len(buckets) == 25
    assert all(b["count"] == 0 for b in buckets)
