"""調査結果キャッシュのダイジェスト・チャット付記用ブロック生成。

調査結果は LLM プロンプトには混ぜず、生成済み本文の末尾にサーバ側で連結する
（設計判断 #13: 出典 URL の改変・捏造の余地を排除する）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import EventRecord, EventTypeResearch
from vcenter_event_assistant.services.research.research_service import (
    RESEARCH_DISCLAIMER,
    RESEARCH_STATUS_OK,
)
from vcenter_event_assistant.settings import Settings

RESEARCH_SECTION_HEADING = "## 関連調査情報（自動 WEB 調査）"


@dataclass(frozen=True)
class ResearchAttachmentItem:
    """付記 1 件分（event_type 単位の調査結果 + 期間内の最大スコア）。"""

    event_type: str
    max_score: int
    summary: str | None
    sources: list[dict[str, str]]
    searched_at: datetime


async def select_research_for_window(
    session: AsyncSession,
    *,
    from_utc: datetime,
    to_utc: datetime,
    settings: Settings,
) -> list[ResearchAttachmentItem]:
    """期間内の高スコア event_type に対する調査結果をスコア降順で最大 N 件返す。

    付記対象は ``status=ok`` の行のみ（no_result / error は出さない）。
    TTL 切れでも取得済みキャッシュは付記する（TTL は再調査の判定にのみ使う）。
    """
    res = await session.execute(
        select(
            EventRecord.event_type,
            func.max(EventRecord.notable_score).label("max_score"),
        )
        .where(
            EventRecord.occurred_at >= from_utc,
            EventRecord.occurred_at < to_utc,
            EventRecord.notable_score >= settings.research_event_score_threshold,
        )
        .group_by(EventRecord.event_type)
        .order_by(desc("max_score"))
    )
    score_by_type = {row[0]: int(row[1]) for row in res.all()}
    if not score_by_type:
        return []

    res = await session.execute(
        select(EventTypeResearch).where(
            EventTypeResearch.event_type.in_(score_by_type.keys()),
            EventTypeResearch.status == RESEARCH_STATUS_OK,
        )
    )
    research_by_type = {row.event_type: row for row in res.scalars().all()}

    items: list[ResearchAttachmentItem] = []
    for event_type in sorted(
        score_by_type, key=lambda t: score_by_type[t], reverse=True
    ):
        row = research_by_type.get(event_type)
        if row is None:
            continue
        items.append(
            ResearchAttachmentItem(
                event_type=event_type,
                max_score=score_by_type[event_type],
                summary=row.summary,
                sources=list(row.sources or []),
                searched_at=row.searched_at,
            )
        )
        if len(items) >= settings.research_attach_max_items:
            break
    return items


def render_research_attachment(items: list[ResearchAttachmentItem]) -> str | None:
    """付記ブロックの Markdown を返す。対象がなければ ``None``。"""
    if not items:
        return None

    lines = [RESEARCH_SECTION_HEADING, "", f"> {RESEARCH_DISCLAIMER}", ""]
    for item in items:
        searched_at = item.searched_at
        if searched_at.tzinfo is None:
            searched_at = searched_at.replace(tzinfo=timezone.utc)
        lines.append(
            f"### {item.event_type}（最大スコア {item.max_score} / "
            f"調査日 {searched_at.date().isoformat()}）"
        )
        lines.append("")
        if item.summary:
            lines.append(item.summary)
            lines.append("")
        if item.sources:
            lines.append("出典:")
            for source in item.sources:
                title = source.get("title") or source.get("url", "")
                url = source.get("url", "")
                lines.append(f"- [{title}]({url})")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def build_research_attachment_markdown(
    session: AsyncSession,
    *,
    from_utc: datetime,
    to_utc: datetime,
    settings: Settings,
) -> str | None:
    """期間に対応する付記ブロック Markdown を返す（対象がなければ ``None``）。"""
    items = await select_research_for_window(
        session,
        from_utc=from_utc,
        to_utc=to_utc,
        settings=settings,
    )
    return render_research_attachment(items)
