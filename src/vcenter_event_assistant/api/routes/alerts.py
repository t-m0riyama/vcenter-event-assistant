from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import (
    AlertRuleRead, AlertRuleCreate, AlertRuleUpdate,
    AlertHistoryListResponse, AlertHistoryRead, AlertRulesImportRequest,
    AlertRulesImportResponse, AlertStateResolveRequest,
)
from vcenter_event_assistant.db.models import AlertRule, AlertHistory, AlertState
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _is_alert_rule_name_unique_violation(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if isinstance(constraint_name, str) and constraint_name:
        lowered = constraint_name.lower()
        if "alert" in lowered and "name" in lowered:
            return True

    parts = [str(exc)]
    if orig is not None:
        parts.append(str(orig))
    message = " ".join(parts).lower()
    return "unique" in message and "alert_rules" in message and "name" in message

@router.get("/rules", response_model=list[AlertRuleRead])
async def list_alert_rules(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(AlertRule).order_by(AlertRule.name.asc()))
    return list(res.scalars().all())

@router.post("/rules", response_model=AlertRuleRead, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(body: AlertRuleCreate, session: AsyncSession = Depends(get_session)):
    # 同名のルールがないかチェック
    res = await session.execute(select(AlertRule.id).where(AlertRule.name == body.name))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Alert rule with this name already exists")
    
    rule = AlertRule(
        name=body.name,
        rule_type=body.rule_type,
        is_enabled=body.is_enabled,
        alert_level=body.alert_level,
        config=body.config,
    )
    session.add(rule)
    try:
        await session.flush()
    except IntegrityError as exc:
        if _is_alert_rule_name_unique_violation(exc):
            raise HTTPException(status_code=409, detail="Alert rule with this name already exists") from exc
        raise
    await session.refresh(rule)
    return rule

@router.patch("/rules/{rule_id}", response_model=AlertRuleRead)
async def patch_alert_rule(rule_id: int, body: AlertRuleUpdate, session: AsyncSession = Depends(get_session)):
    rule = await session.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    previous_name = rule.name
    name_changed = body.name is not None and body.name != previous_name
    
    if body.name is not None:
        existing = await session.execute(
            select(AlertRule.id).where(AlertRule.name == body.name, AlertRule.id != rule_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Alert rule with this name already exists")
        rule.name = body.name
    if body.is_enabled is not None:
        rule.is_enabled = body.is_enabled
    if body.config is not None:
        rule.config = body.config
    if body.alert_level is not None:
        rule.alert_level = body.alert_level

    try:
        await session.flush()
    except IntegrityError as exc:
        if name_changed and _is_alert_rule_name_unique_violation(exc):
            raise HTTPException(status_code=409, detail="Alert rule with this name already exists") from exc
        raise
    await session.refresh(rule)
    return rule

@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    rule = await session.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    await session.delete(rule)
    await session.flush()


@router.post("/rules/import", response_model=AlertRulesImportResponse)
async def import_alert_rules(
    body: AlertRulesImportRequest,
    session: AsyncSession = Depends(get_session),
) -> AlertRulesImportResponse:
    names_in_file = [rule.name for rule in body.rules]
    if len(names_in_file) != len(set(names_in_file)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="duplicate name in rules",
        )

    for imported_rule in body.rules:
        res = await session.execute(select(AlertRule).where(AlertRule.name == imported_rule.name))
        existing = res.scalar_one_or_none()
        if existing is None:
            session.add(
                AlertRule(
                    name=imported_rule.name,
                    rule_type=imported_rule.rule_type,
                    is_enabled=imported_rule.is_enabled,
                    alert_level=imported_rule.alert_level,
                    config=imported_rule.config,
                ),
            )
        elif body.overwrite_existing:
            existing.rule_type = imported_rule.rule_type
            existing.is_enabled = imported_rule.is_enabled
            existing.alert_level = imported_rule.alert_level
            existing.config = imported_rule.config

    if body.delete_rules_not_in_import:
        names = set(names_in_file)
        if not names:
            await session.execute(delete(AlertRule))
        else:
            await session.execute(delete(AlertRule).where(~AlertRule.name.in_(sorted(names))))

    await session.flush()

    count_res = await session.execute(select(AlertRule.id))
    rules_count = len(list(count_res.scalars().all()))
    return AlertRulesImportResponse(rules_count=rules_count)

def _history_item_to_read(
    item: AlertHistory,
    firing_keys: set[tuple[int, str]],
) -> AlertHistoryRead:
    rule_type = item.rule.rule_type if item.rule else ""
    can_resolve = (
        rule_type == "event_score"
        and (item.rule_id, item.context_key) in firing_keys
    )
    return AlertHistoryRead(
        id=item.id,
        rule_id=item.rule_id,
        rule_name=item.rule.name if item.rule else None,
        rule_type=rule_type,
        alert_level=item.alert_level,
        state=item.state,
        context_key=item.context_key,
        notified_at=item.notified_at,
        channel=item.channel,
        success=item.success,
        error_message=item.error_message,
        can_resolve=can_resolve,
    )


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
    items = list(res.scalars().all())

    firing_keys: set[tuple[int, str]] = set()
    rule_ids = {item.rule_id for item in items}
    if rule_ids:
        firing_res = await session.execute(
            select(AlertState.rule_id, AlertState.context_key)
            .join(AlertRule, AlertRule.id == AlertState.rule_id)
            .where(
                AlertState.state == "firing",
                AlertRule.rule_type == "event_score",
                AlertState.rule_id.in_(rule_ids),
            )
        )
        firing_keys = {(row.rule_id, row.context_key) for row in firing_res.all()}

    return AlertHistoryListResponse(
        items=[_history_item_to_read(item, firing_keys) for item in items],
        total=total,
    )


@router.post("/states/resolve", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_alert_state(body: AlertStateResolveRequest) -> None:
    evaluator = AlertEvaluator()
    try:
        await evaluator.resolve_event_score_manually(body.rule_id, body.context_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/history/{history_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_history(
    history_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    history = await session.get(AlertHistory, history_id)
    if history is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert history not found")
    await session.delete(history)
    await session.flush()
