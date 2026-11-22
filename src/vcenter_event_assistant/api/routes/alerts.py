from __future__ import annotations
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select, desc, func, update
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
from vcenter_event_assistant.db.models import AlertRule, AlertHistory, AlertState
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.alerting.alert_entity_resolution import (
    MetricProbe,
    ResolvedEntity,
    collect_metric_probes,
    metric_name_lookback,
    metric_probe,
    resolve_metric_entities_at,
)
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
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

@router.post("/rules", dependencies=[RequireAdmin], response_model=AlertRuleRead, status_code=status.HTTP_201_CREATED)
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
    statement = (
        update(AlertRule)
        .where(AlertRule.id == rule_id, AlertRule.revision == body.revision)
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

    existing_id = await session.scalar(select(AlertRule.id).where(AlertRule.id == rule_id))
    if existing_id is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
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

    for imported_rule in body.rules:
        values = imported_rule.model_dump(exclude={"name"})
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

async def _resolve_history_entities(
    session: AsyncSession, items: list[AlertHistory], perf_sample_interval_seconds: int
) -> dict[MetricProbe, ResolvedEntity]:
    """ページ内の metric_threshold 行の対象名を、タイムラインと同じ関数でまとめて引く（N+1 にしない）。

    名前は行ごとに「その行のルールの指標の、``occurred_at`` の時点の名前」。ページの区切りや同じページに
    居合わせるほかの行に依存しないので、行の「タイムラインで見る」リンク（``occurred_at`` の前後・
    ``entity_name`` で絞る）で開いたタイムラインにも同じ名前で出る。1 ページ（最大 200 件）は 1 本の問い合わせで
    引ける（ルールに ``metric_key`` が無い古い行が混じるときだけ 2 本）。
    """
    probes = collect_metric_probes(
        (
            item.rule.rule_type if item.rule else "",
            item.context_key,
            item.rule.config if item.rule else None,
            item.occurred_at,
        )
        for item in items
    )
    return await resolve_metric_entities_at(
        session, probes, lookback=metric_name_lookback(perf_sample_interval_seconds)
    )


def _history_item_to_read(
    item: AlertHistory,
    firing_keys: set[tuple[int, str]],
    entities: Mapping[MetricProbe, ResolvedEntity] | None = None,
) -> AlertHistoryRead:
    rule_type = item.rule.rule_type if item.rule else ""
    can_resolve = (
        rule_type == "event_score"
        and (item.rule_id, item.context_key) in firing_keys
    )
    vcenter_id: uuid.UUID | None = None
    entity_name: str | None = None
    if rule_type == "metric_threshold":
        probe = metric_probe(item.context_key, item.rule.config if item.rule else None, item.occurred_at)
        if probe is not None:
            vcenter_id = probe[0]
            hit = (entities or {}).get(probe)
            entity_name = hit.name if hit is not None else None
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
        vcenter_id=vcenter_id,
        entity_name=entity_name,
        channel=item.channel,
        success=item.success,
        error_message=item.error_message,
        delivery_status=item.delivery_status,
        attempt_count=item.attempt_count,
        last_attempt_at=item.last_attempt_at,
        next_attempt_at=item.next_attempt_at,
        can_resolve=can_resolve,
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
                AlertRule.rule_type == "event_score",
                AlertState.rule_id.in_(rule_ids),
            )
        )
        firing_keys = {(row.rule_id, row.context_key) for row in firing_res.all()}

    entities = await _resolve_history_entities(session, items, settings.perf_sample_interval_seconds)

    return AlertHistoryListResponse(
        items=[_history_item_to_read(item, firing_keys, entities) for item in items],
        total=total,
    )


@router.post("/states/resolve", dependencies=[RequireOperator], status_code=status.HTTP_204_NO_CONTENT)
async def resolve_alert_state(
    body: AlertStateResolveRequest,
    settings: Settings = Depends(get_app_settings),
) -> None:
    evaluator = AlertEvaluator(settings)
    try:
        await evaluator.resolve_event_score_manually(body.rule_id, body.context_key)
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
