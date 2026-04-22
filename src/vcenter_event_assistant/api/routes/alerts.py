from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import (
    AlertRuleRead, AlertRuleCreate, AlertRuleUpdate,
    AlertHistoryListResponse
)
from vcenter_event_assistant.db.models import AlertRule, AlertHistory

router = APIRouter(prefix="/alerts", tags=["alerts"])

@router.get("/rules", response_model=list[AlertRuleRead])
async def list_alert_rules(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(AlertRule).order_by(AlertRule.name.asc()))
    return list(res.scalars().all())

@router.post("/rules", response_model=AlertRuleRead, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(body: AlertRuleCreate, session: AsyncSession = Depends(get_session)):
    # 同名のルールがないかチェック
    res = await session.execute(select(AlertRule).where(AlertRule.name == body.name))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Alert rule with this name already exists")
    
    rule = AlertRule(
        name=body.name,
        rule_type=body.rule_type,
        is_enabled=body.is_enabled,
        config=body.config
    )
    session.add(rule)
    await session.flush()
    await session.refresh(rule)
    return rule

@router.patch("/rules/{rule_id}", response_model=AlertRuleRead)
async def patch_alert_rule(rule_id: int, body: AlertRuleUpdate, session: AsyncSession = Depends(get_session)):
    rule = await session.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    
    if body.name is not None:
        rule.name = body.name
    if body.is_enabled is not None:
        rule.is_enabled = body.is_enabled
    if body.config is not None:
        rule.config = body.config
    
    await session.flush()
    await session.refresh(rule)
    return rule

@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    rule = await session.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    await session.delete(rule)
    await session.flush()

@router.get("/history", response_model=AlertHistoryListResponse)
async def list_alert_history(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session)
):
    # 合計件数
    count_res = await session.execute(select(func.count(AlertHistory.id)))
    total = count_res.scalar_one()
    
    # 履歴取得 (rule を結合して名前を取得できるようにする)
    res = await session.execute(
        select(AlertHistory)
        .options(selectinload(AlertHistory.rule))
        .order_by(desc(AlertHistory.notified_at))
        .limit(limit)
        .offset(offset)
    )
    items = res.scalars().all()
    
    return AlertHistoryListResponse(items=list(items), total=total)
