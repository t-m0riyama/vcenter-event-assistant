"""モックインベントリと HA の移動履歴をシードする。"""

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import InventorySyncState, VCenter
from vcenter_event_assistant.mocks.mock_inventory import (
    MOCK_INVENTORY_SLOT_SECONDS,
    SCREENSHOT_VCENTER_NAME,
    mock_inventory,
)
from vcenter_event_assistant.services.inventory import persist_inventory


async def seed_inventory(
    session: AsyncSession, vcenter: VCenter, now: datetime
) -> None:
    """一度の HA 移動を含む観測を、現在のモック構成につながるように保存する。"""
    state = await session.get(InventorySyncState, vcenter.id)
    if state is not None and state.first_success_at is not None:
        return

    earlier = now - timedelta(seconds=MOCK_INVENTORY_SLOT_SECONDS)
    screenshot = vcenter.name == SCREENSHOT_VCENTER_NAME
    # デモのイベントとメトリクスより前から関係を記録する。
    initial = now - timedelta(minutes=70)
    previous = mock_inventory(
        earlier, vcenter_name=vcenter.name, screenshot_before_move=screenshot
    )
    current = mock_inventory(now, vcenter_name=vcenter.name)
    for observed_at, observation in (
        (initial, previous),
        (earlier, previous),
        (now, current),
    ):
        await persist_inventory(
            session,
            vcenter.id,
            observation,
            observed_at=observed_at,
            started_at=observed_at,
        )
        await session.flush()
