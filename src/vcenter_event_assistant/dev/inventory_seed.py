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
    # デモのホストの障害（54〜48 分前）の直後に、HA で VM が移ったことにする。
    moved_at = now - timedelta(minutes=40)
    previous = mock_inventory(
        earlier, vcenter_name=vcenter.name, screenshot_before_move=screenshot
    )
    current = mock_inventory(now, vcenter_name=vcenter.name)
    # 既定の収集の間隔（10 分）ごとに観測を入れ、観測の間が空いた（stale）ように見せない。
    observations = []
    observed_at = initial
    while observed_at < now:
        observations.append(
            (observed_at, previous if observed_at < moved_at else current)
        )
        observed_at += timedelta(minutes=10)
    observations.append((now, current))
    for observed_at, observation in observations:
        await persist_inventory(
            session,
            vcenter.id,
            observation,
            observed_at=observed_at,
            started_at=observed_at,
        )
        await session.flush()
