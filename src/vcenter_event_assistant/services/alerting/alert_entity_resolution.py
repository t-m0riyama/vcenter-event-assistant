"""アラートの対象（vCenter と対象名）の解決。タイムラインと通知履歴で同じ規則を使う。

- ``metric_threshold``: ``context_key`` は ``{vcenter_id}:{entity_moid}``。vCenter と moid を取り出し、
  ``MetricSample`` の名前で対象名を引く。旧形式（moid だけ）は vCenter が分からず、moid は vCenter をまたいで
  重複し得るので、解決しない。
- ``event_score``: ``context_key`` はイベント種別。vCenter も対象も持たない。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.db.models import MetricSample
from vcenter_event_assistant.services.alerting.alert_eval_common import is_vcenter_scoped_context_key

# 期間の開始からさかのぼって、メトリクスの対象名を探す幅の最小値。metric_name_lookback を参照。
_METRIC_NAME_LOOKBACK_MIN = timedelta(hours=6)
# IN に並べる値の数の上限（SQLite / asyncpg のバインド変数の上限に当たらないよう分割する）。
IN_CHUNK_SIZE = 500

_T = TypeVar("_T")


def chunks(values: Sequence[_T], size: int) -> Iterator[list[_T]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def metric_name_lookback(perf_sample_interval_seconds: int) -> timedelta:
    """metric アラートの対象名を探すとき、期間の開始からさかのぼる幅。

    収集間隔の 12 回分か 6 時間の長いほう。既定の 5 分間隔なら 72 回分あり、収集の一時的な停止
    （vCenter の再起動や接続断で数十分〜数時間）をまたいでも名前を引ける。一方で全期間は読まないので、
    走査する行数は対象ごとに保持期間ではなくこの幅で決まる。
    """
    return max(_METRIC_NAME_LOOKBACK_MIN, timedelta(seconds=12 * perf_sample_interval_seconds))


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    name: str
    entity_type: str | None


def parse_metric_context_key(context_key: str) -> tuple[uuid.UUID, str] | None:
    """``{vcenter_id}:{entity_moid}`` を分解する。旧形式（moid だけ）は None。"""
    if not is_vcenter_scoped_context_key(context_key):
        return None
    prefix, moid = context_key.split(":", 1)
    return uuid.UUID(prefix), moid


def metric_key_of(config: Any) -> str | None:
    if isinstance(config, Mapping):
        value = config.get("metric_key")
        if isinstance(value, str) and value:
            return value
    return None


def collect_metric_targets(
    rows: Iterable[tuple[str, str, Any]],
) -> tuple[set[tuple[uuid.UUID, str]], set[str] | None]:
    """``(rule_type, context_key, rule_config)`` の列から、名前を引く対象と、見る指標を求める。

    返す指標の集合は、対象のルールがすべて ``metric_key`` を持つときだけ（1 つでも持たなければ None で、
    ``resolve_metric_entities`` は指標を絞らない）。
    """
    targets: set[tuple[uuid.UUID, str]] = set()
    keys: set[str] = set()
    every_rule_has_metric_key = True
    for rule_type, context_key, rule_config in rows:
        if rule_type != "metric_threshold":
            continue
        parsed = parse_metric_context_key(context_key)
        if parsed is None:
            continue
        targets.add(parsed)
        metric_key = metric_key_of(rule_config)
        if metric_key is None:
            every_rule_has_metric_key = False
        else:
            keys.add(metric_key)
    return targets, (keys if every_rule_has_metric_key else None)


async def resolve_metric_entities(
    session: AsyncSession,
    targets: set[tuple[uuid.UUID, str]],
    metric_keys: set[str] | None,
    *,
    sampled_from: datetime,
    sampled_to: datetime,
) -> dict[tuple[uuid.UUID, str], ResolvedEntity]:
    """``(vcenter_id, entity_moid)`` ごとに、期間の終わりに最も近いサンプルの名前と種類を返す。

    見るのは ``sampled_from <= sampled_at <= sampled_to`` のサンプルだけで、障害当時の名前を引く
    （期間より後の改名を拾わず、全期間も読まない）。範囲にサンプルが無ければ解決しない。

    ``(vcenter_id, entity_moid, metric_key)`` ごとの ``MAX(sampled_at)`` を GROUP BY で求めてから元の行と
    JOIN する。複合インデックス ``(vcenter_id, entity_moid, metric_key, sampled_at)`` がそのまま効く形で、
    JOIN の 4 列は一意制約 ``uq_metric_sample_point`` の列なので行は 1 つに決まる。指標をまたいだ最新は
    Python 側で選ぶ。``metric_keys`` を渡すとその指標だけを見る。名前が空文字のときは解決しない。
    """
    if not targets:
        return {}
    vcenter_ids = sorted({vid for vid, _ in targets}, key=str)
    best: dict[tuple[uuid.UUID, str], tuple[datetime, int, str, str | None]] = {}
    for moids in chunks(sorted({moid for _, moid in targets}), IN_CHUNK_SIZE):
        clauses: list[ColumnElement[bool]] = [
            MetricSample.vcenter_id.in_(vcenter_ids),
            MetricSample.entity_moid.in_(moids),
            MetricSample.sampled_at >= sampled_from,
            MetricSample.sampled_at <= sampled_to,
        ]
        if metric_keys:
            clauses.append(MetricSample.metric_key.in_(sorted(metric_keys)))
        latest = (
            select(
                MetricSample.vcenter_id.label("vcenter_id"),
                MetricSample.entity_moid.label("entity_moid"),
                MetricSample.metric_key.label("metric_key"),
                func.max(MetricSample.sampled_at).label("max_sampled_at"),
            )
            .where(*clauses)
            .group_by(MetricSample.vcenter_id, MetricSample.entity_moid, MetricSample.metric_key)
            .subquery("latest")
        )
        stmt = select(
            MetricSample.vcenter_id,
            MetricSample.entity_moid,
            MetricSample.sampled_at,
            MetricSample.id,
            MetricSample.entity_name,
            MetricSample.entity_type,
        ).join(
            latest,
            and_(
                MetricSample.vcenter_id == latest.c.vcenter_id,
                MetricSample.entity_moid == latest.c.entity_moid,
                MetricSample.metric_key == latest.c.metric_key,
                MetricSample.sampled_at == latest.c.max_sampled_at,
            ),
        )
        for vid, moid, sampled_at, sid, name, etype in (await session.execute(stmt)).all():
            key = (vid, moid)
            if key not in targets:
                continue
            candidate = (to_utc(sampled_at), int(sid), name, etype)
            current = best.get(key)
            if current is None or candidate[:2] > current[:2]:
                best[key] = candidate
    return {
        key: ResolvedEntity(name=name, entity_type=etype or None)
        for key, (_, _, name, etype) in best.items()
        if name
    }
