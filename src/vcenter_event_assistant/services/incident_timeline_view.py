"""タイムライン画面専用 API（``POST /api/incident-timeline/view``）のサービス。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.schemas.incident_timeline_view import (
    IncidentTimelineViewRequest,
    IncidentTimelineViewResponse,
)


async def build_incident_timeline_view(
    session: AsyncSession,
    body: IncidentTimelineViewRequest,
    *,
    owner_key: str,
) -> IncidentTimelineViewResponse:
    """期間内のイベントとアラートを、個々の出来事として時刻順に返す。

    ``owner_key`` は同時実行数の上限（``aggregation_slot``）を利用者ごとに数えるための識別子。
    PR1 では ``event`` と ``alert`` だけを扱い、``metric`` と ``log`` は後の PR で足す。
    """
    raise NotImplementedError
