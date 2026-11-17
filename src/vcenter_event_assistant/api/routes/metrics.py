"""Metric time series API."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.api.auth_deps import RequireViewer
from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.deps import get_session
from vcenter_event_assistant.api.schemas import MetricKeysResponse, MetricPoint, MetricSeriesResponse
from vcenter_event_assistant.api.schemas.metrics import MetricCatalogResponse, MetricDefinitionRead
from vcenter_event_assistant.db.models import MetricSample
from vcenter_event_assistant.plugins.registry import get_collector_registry
from vcenter_event_assistant.services.metric_vcenter_filter import metric_vcenter_clause

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/catalog", dependencies=[RequireViewer], response_model=MetricCatalogResponse)
async def metric_catalog() -> MetricCatalogResponse:
    return MetricCatalogResponse(metrics=[
        MetricDefinitionRead(collector_id=collector_id, key=d.key, display_name=d.display_name,
                             unit=d.unit, entity_type=d.entity_type, series_mode=d.series_mode,
                             category=d.category, description=d.description)
        for collector_id, d in get_collector_registry().metric_catalog()
    ])


async def _metric_list_vcenter_clauses(
    session: AsyncSession,
    vcenter_id: uuid.UUID | None,
    *,
    dialect_name: str,
) -> list[ColumnElement[bool]] | None:
    """メトリクス一覧の vCenter の条件を返す。

    指定したときは方言に関係なく、その vCenter で絞る。指定しないときに登録済みの vCenter の id を並べる
    （``metric_vcenter_clause``）のは SQLite のときだけ。SQLite は統計が無いと ix_metric_samples_metric_key を選び、
    期間に関係なくその指標の全サンプルを読むため（約 323 万行で、24 時間の件数・一覧がそれぞれ約 10 秒。Issue #324）。
    PostgreSQL には vcenter_id・metric_key を前に置いた索引が無く（ix_metric_samples_vcenter_metric_sampled_value は
    SQLite だけに作る）、計測（PostgreSQL 16、約 323 万行）では、当てても 5 ケースは計画も時間も変わらず、
    期間なしの件数だけが metric_key の索引だけで数えられなくなって表を読み、9.9 ms から 125.8 ms に遅くなったため。

    Returns:
        条件のリスト（PostgreSQL で未指定のときは空）。SQLite で vCenter が 1 つも無いときは ``None``
        （サンプルも無いので、呼び出し側は問い合わせずに空の結果を返す）。
    """
    if vcenter_id is None and dialect_name != "sqlite":
        return []
    clause = await metric_vcenter_clause(session, vcenter_id)
    return None if clause is None else [clause]


def _metric_filter_clauses(
    *,
    metric_key: str,
    vcenter_clauses: list[ColumnElement[bool]],
    from_time: datetime | None,
    to_time: datetime | None,
    entity_moid: str | None,
) -> list:
    clauses = [MetricSample.metric_key == metric_key, *vcenter_clauses]
    if from_time is not None:
        clauses.append(MetricSample.sampled_at >= to_utc(from_time))
    if to_time is not None:
        clauses.append(MetricSample.sampled_at <= to_utc(to_time))
    if entity_moid is not None:
        clauses.append(MetricSample.entity_moid == entity_moid)
    return clauses


@router.get("/keys", dependencies=[RequireViewer], response_model=MetricKeysResponse)
async def list_metric_keys(
    session: AsyncSession = Depends(get_session),
    vcenter_id: uuid.UUID | None = None,
) -> MetricKeysResponse:
    q = select(MetricSample.metric_key).distinct()
    if vcenter_id is not None:
        q = q.where(MetricSample.vcenter_id == vcenter_id)
    q = q.order_by(MetricSample.metric_key.asc())
    res = await session.execute(q)
    keys = [row[0] for row in res.all()]
    return MetricKeysResponse(metric_keys=keys)


@router.get("", dependencies=[RequireViewer], response_model=MetricSeriesResponse)
async def list_metrics(
    response: Response,
    session: AsyncSession = Depends(get_session),
    vcenter_id: uuid.UUID | None = None,
    metric_key: str = Query(..., min_length=1, max_length=256),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    entity_moid: str | None = None,
    limit: int = Query(default=2000, ge=1, le=10000),
) -> MetricSeriesResponse:
    bind = session.get_bind()
    vcenter_clauses = await _metric_list_vcenter_clauses(
        session,
        vcenter_id,
        dialect_name=bind.dialect.name if bind is not None else "sqlite",
    )
    if vcenter_clauses is None:
        response.headers["X-Total-Count"] = "0"
        return MetricSeriesResponse(points=[], total=0)
    clauses = _metric_filter_clauses(
        metric_key=metric_key,
        vcenter_clauses=vcenter_clauses,
        from_time=from_time,
        to_time=to_time,
        entity_moid=entity_moid,
    )

    count_q = select(func.count()).select_from(MetricSample).where(*clauses)
    total = int((await session.execute(count_q)).scalar_one() or 0)

    q = (
        select(MetricSample)
        .where(*clauses)
        .order_by(MetricSample.sampled_at.asc())
        .limit(limit)
    )
    res = await session.execute(q)
    rows = list(res.scalars().all())
    points = [
        MetricPoint(
            sampled_at=r.sampled_at,
            value=r.value,
            entity_name=r.entity_name,
            entity_moid=r.entity_moid,
            metric_key=r.metric_key,
            vcenter_id=r.vcenter_id,
            collector_id=r.collector_id,
        )
        for r in rows
    ]
    response.headers["X-Total-Count"] = str(total)
    return MetricSeriesResponse(points=points, total=total)
