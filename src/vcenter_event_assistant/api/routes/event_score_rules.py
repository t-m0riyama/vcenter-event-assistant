"""CRUD for per-event-type notable score deltas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import EventScoreRuleCreate, EventScoreRuleRead, EventScoreRuleUpdate
from vcenter_event_assistant.db.models import EventScoreRule
from vcenter_event_assistant.services.event_scores import recalculate_notable_scores_for_event_type

router = APIRouter(prefix="/event-score-rules", tags=["event-score-rules"])


@router.get("", response_model=list[EventScoreRuleRead])
async def list_event_score_rules(
    session: AsyncSession = Depends(get_session),
) -> list[EventScoreRule]:
    res = await session.execute(select(EventScoreRule).order_by(EventScoreRule.event_type.asc()))
    return list(res.scalars().all())


@router.post("", response_model=EventScoreRuleRead, status_code=status.HTTP_201_CREATED)
async def create_event_score_rule(
    body: EventScoreRuleCreate,
    session: AsyncSession = Depends(get_session),
) -> EventScoreRule:
    if not body.event_type.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="event_type is required")
    dup = await session.execute(select(EventScoreRule.id).where(EventScoreRule.event_type == body.event_type))
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="rule for this event_type already exists",
        )
    rule = EventScoreRule(event_type=body.event_type, score_delta=body.score_delta)
    session.add(rule)
    await session.flush()
    await session.refresh(rule)
    await recalculate_notable_scores_for_event_type(
        session,
        event_type=rule.event_type,
        score_delta=rule.score_delta,
    )
    return rule


@router.patch("/{rule_id}", response_model=EventScoreRuleRead)
async def patch_event_score_rule(
    rule_id: int,
    body: EventScoreRuleUpdate,
    session: AsyncSession = Depends(get_session),
) -> EventScoreRule:
    row = await session.get(EventScoreRule, rule_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    row.score_delta = body.score_delta
    await session.flush()
    await recalculate_notable_scores_for_event_type(
        session,
        event_type=row.event_type,
        score_delta=row.score_delta,
    )
    await session.refresh(row)
    return row


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_score_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(EventScoreRule, rule_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    et = row.event_type
    await session.delete(row)
    await session.flush()
    await recalculate_notable_scores_for_event_type(session, event_type=et, score_delta=0)
