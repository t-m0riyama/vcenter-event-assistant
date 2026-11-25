from __future__ import annotations
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, delete, desc, func, literal, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from vcenter_event_assistant.api.auth_deps import RequireAdmin, RequireOperator, RequireViewer
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.import_guards import reject_empty_destructive_import
from vcenter_event_assistant.api.schemas import (
    AlertRuleRead, AlertRuleCreate, AlertRuleUpdate,
    AlertHistoryListResponse, AlertHistoryRead, AlertRulesImportRequest,
    AlertRulesImportResponse, AlertStateResolveRequest,
)
from vcenter_event_assistant.api.schemas.alerts import (
    AlertRuleType,
    ensure_alert_rule_config_json,
    validate_alert_rule_config,
)
from vcenter_event_assistant.db.models import AlertRule, AlertHistory, AlertState
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alert_history_read import AlertHistoryTarget, resolve_alert_history_targets
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.services.alerting.alert_eval_common import MANUALLY_RESOLVABLE_RULE_TYPES
from vcenter_event_assistant.settings import Settings

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

@router.get("/rules", dependencies=[RequireViewer], response_model=list[AlertRuleRead])
async def list_alert_rules(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(AlertRule).order_by(AlertRule.name.asc()))
    return list(res.scalars().all())

def _config_for_save(body: AlertRuleCreate) -> dict:
    try:
        ensure_alert_rule_config_json(body.config)
        return validate_alert_rule_config(body.rule_type, body.config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/rules", dependencies=[RequireAdmin], response_model=AlertRuleRead, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(body: AlertRuleCreate, session: AsyncSession = Depends(get_session)):
    config = _config_for_save(body)
    # 同名のルールがないかチェック
    res = await session.execute(select(AlertRule.id).where(AlertRule.name == body.name))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Alert rule with this name already exists")
    
    rule = AlertRule(
        name=body.name,
        rule_type=body.rule_type,
        is_enabled=body.is_enabled,
        alert_level=body.alert_level,
        config=config,
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

async def _alert_rule_update_session(
    settings: Settings = Depends(get_app_settings),
) -> AsyncIterator[AsyncSession]:
    async with session_scope(settings=settings, isolate_memory=True) as session:
        yield session


@router.patch("/rules/{rule_id}", dependencies=[RequireAdmin], response_model=AlertRuleRead)
async def patch_alert_rule(
    rule_id: int,
    body: AlertRuleUpdate,
    session: AsyncSession = Depends(_alert_rule_update_session, scope="function"),
):
    changes = body.model_dump(exclude={"revision"}, exclude_none=True)
    criteria = [AlertRule.id == rule_id, AlertRule.revision == body.revision]
    config_errors: dict[str, str] = {}
    if body.config is not None:
        try:
            ensure_alert_rule_config_json(body.config)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        for rule_type in get_args(AlertRuleType):
            try:
                config = validate_alert_rule_config(rule_type, body.config)
            except ValueError as exc:
                config_errors[rule_type] = str(exc)
                continue
            if config != body.config:
                # 対象の種類と版を更新文で確かめてから、その種類の正規化を適用する。
                config_type = AlertRule.__table__.c.config.type
                changes["config"] = case(
                    (AlertRule.rule_type == rule_type, literal(config, type_=config_type)),
                    else_=literal(body.config, type_=config_type),
                )
        if config_errors:
            criteria.append(AlertRule.rule_type.not_in(list(config_errors)))
    # 更新前に読み取ると、SQLite の同時更新で書き込み待ちと競合する。
    statement = (
        update(AlertRule)
        .where(*criteria)
        .values(**changes, revision=uuid.uuid4())
        .returning(AlertRule)
    )
    try:
        rule = (await session.scalars(statement)).one_or_none()
    except IntegrityError as exc:
        if _is_alert_rule_name_unique_violation(exc):
            raise HTTPException(status_code=409, detail="Alert rule with this name already exists") from exc
        raise
    if rule is not None:
        return rule

    existing = (await session.execute(
        select(AlertRule.revision, AlertRule.rule_type).where(AlertRule.id == rule_id)
    )).one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    if existing.revision == body.revision and existing.rule_type in config_errors:
        raise HTTPException(status_code=422, detail=config_errors[existing.rule_type])
    raise HTTPException(
        status_code=409,
        detail="Alert rule has changed since it was read",
        headers={"X-VEA-Error-Code": "alert_rule_stale"},
    )

@router.delete("/rules/{rule_id}", dependencies=[RequireAdmin], status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    rule = await session.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    await session.delete(rule)
    await session.flush()


@router.post("/rules/import", dependencies=[RequireAdmin], response_model=AlertRulesImportResponse)
async def import_alert_rules(
    body: AlertRulesImportRequest,
    session: AsyncSession = Depends(get_session),
) -> AlertRulesImportResponse:
    configs = [_config_for_save(rule) for rule in body.rules]
    names_in_file = [rule.name for rule in body.rules]
    if len(names_in_file) != len(set(names_in_file)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="duplicate name in rules",
        )

    if body.delete_rules_not_in_import:
        reject_empty_destructive_import(
            item_count=len(body.rules),
            delete_not_in_import=True,
            resource_label="alert rules",
        )

    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

    for imported_rule, config in zip(body.rules, configs, strict=True):
        values = imported_rule.model_dump(exclude={"name", "config"})
        values["config"] = config
        values["revision"] = uuid.uuid4()
        statement = dialect_insert(AlertRule).values(name=imported_rule.name, **values)
        if body.overwrite_existing:
            statement = statement.on_conflict_do_update(index_elements=[AlertRule.name], set_=values)
        else:
            statement = statement.on_conflict_do_nothing(index_elements=[AlertRule.name])
        await session.execute(statement)

    if body.delete_rules_not_in_import:
        await session.execute(delete(AlertRule).where(~AlertRule.name.in_(names_in_file)))

    rules_count = (await session.execute(select(func.count()).select_from(AlertRule))).scalar_one()
    return AlertRulesImportResponse(rules_count=rules_count)

def _history_item_to_read(
    item: AlertHistory, target: AlertHistoryTarget, firing_keys: set[tuple[int, str]],
) -> AlertHistoryRead:
    rule_type = item.rule.rule_type if item.rule else ""
    return AlertHistoryRead(
        id=item.id,
        rule_id=item.rule_id,
        rule_name=item.rule.name if item.rule else None,
        rule_type=rule_type,
        alert_level=item.alert_level,
        state=item.state,
        context_key=item.context_key,
        notified_at=item.notified_at,
        occurred_at=item.occurred_at,
        vcenter_id=target.vcenter_id,
        entity_moid=target.entity_moid,
        entity_name=target.entity_name,
        channel=item.channel,
        success=item.success,
        error_message=item.error_message,
        delivery_status=item.delivery_status,
        attempt_count=item.attempt_count,
        last_attempt_at=item.last_attempt_at,
        next_attempt_at=item.next_attempt_at,
        can_resolve=(
            rule_type in MANUALLY_RESOLVABLE_RULE_TYPES and (item.rule_id, item.context_key) in firing_keys
        ),
    )


@router.get("/history", dependencies=[RequireViewer], response_model=AlertHistoryListResponse)
async def list_alert_history(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
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
                AlertRule.rule_type.in_(MANUALLY_RESOLVABLE_RULE_TYPES),
                AlertState.rule_id.in_(rule_ids),
            )
        )
        firing_keys = {(row.rule_id, row.context_key) for row in firing_res.all()}

    targets = await resolve_alert_history_targets(session, items, settings.perf_sample_interval_seconds)
    return AlertHistoryListResponse(
        items=[_history_item_to_read(item, targets[item.id], firing_keys) for item in items],
        total=total,
    )


@router.post("/states/resolve", dependencies=[RequireOperator], status_code=status.HTTP_204_NO_CONTENT)
async def resolve_alert_state(
    body: AlertStateResolveRequest,
    settings: Settings = Depends(get_app_settings),
) -> None:
    evaluator = AlertEvaluator(settings)
    try:
        await evaluator.resolve_event_alert_manually(body.rule_id, body.context_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/history/{history_id}", dependencies=[RequireAdmin], status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_history(
    history_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    history = await session.get(AlertHistory, history_id)
    if history is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert history not found")
    await session.delete(history)
    await session.flush()
