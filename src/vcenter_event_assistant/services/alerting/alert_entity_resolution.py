"""アラートの対象（vCenter と対象名）の解決。タイムラインと通知履歴で同じ規則を使う。

- ``metric_threshold``: ``context_key`` は ``{vcenter_id}:{entity_moid}``。vCenter と moid を取り出し、
  **そのアラートの ``occurred_at`` の時点の** ``MetricSample`` の名前で対象名を引く（``resolve_metric_entities_at``）。
  旧形式（moid だけ）は vCenter が分からず、moid は vCenter をまたいで重複し得るので、解決しない。
- ``event_score``: ``context_key`` はイベント種別。vCenter も対象も持たない。

名前をアラートの時刻だけで決めるので、表示期間（タイムライン）やページの区切り（通知履歴）が変わっても
同じアラートは同じ名前になる。通知履歴の行のリンク（``entity_name`` で絞る）で開いたタイムラインに、
その行自身が必ず出るのはこのため。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy import Integer, column, select
from sqlalchemy import values as sql_values
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.db.models import MetricSample
from vcenter_event_assistant.services.alerting.alert_eval_common import is_vcenter_scoped_context_key

# アラートの時刻からさかのぼって、メトリクスの対象名を探す幅の最小値。metric_name_lookback を参照。
_METRIC_NAME_LOOKBACK_MIN = timedelta(hours=6)
# IN に並べる値の数の上限（SQLite / asyncpg のバインド変数の上限に当たらないよう分割する）。
IN_CHUNK_SIZE = 500

_T = TypeVar("_T")


def chunks(values: Sequence[_T], size: int) -> Iterator[list[_T]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def metric_name_lookback(perf_sample_interval_seconds: int) -> timedelta:
    """metric アラートの対象名を探すとき、アラートの ``occurred_at`` からさかのぼる幅。

    収集間隔の 12 回分か 6 時間の長いほう。既定の 5 分間隔なら 72 回分あり、収集の一時的な停止
    （vCenter の再起動や接続断で数十分〜数時間）をまたいでも名前を引ける。一方で全期間は読まないので、
    1 件のアラートのために読み得る行数は、保持期間ではなくこの幅で決まる。
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


# 名前を引く 1 件の問い合わせ: (vcenter_id, entity_moid, アラートの occurred_at（UTC）)。
MetricProbe = tuple[uuid.UUID, str, datetime]


def metric_probe(context_key: str, occurred_at: datetime) -> MetricProbe | None:
    """metric_threshold のアラートの ``context_key`` と時刻から、名前を引く組を作る。旧形式の key は None。"""
    parsed = parse_metric_context_key(context_key)
    if parsed is None:
        return None
    return parsed[0], parsed[1], to_utc(occurred_at)


def collect_metric_probes(
    rows: Iterable[tuple[str, str, Any, datetime]],
) -> tuple[set[MetricProbe], set[str] | None]:
    """``(rule_type, context_key, rule_config, occurred_at)`` の列から、名前を引く組と、見る指標を求める。

    組は ``(vcenter_id, entity_moid, occurred_at)`` で重複を除く。返す指標の集合は、対象のルールがすべて
    ``metric_key`` を持つときだけ（1 つでも持たなければ None で、``resolve_metric_entities_at`` は指標を絞らない）。
    """
    probes: set[MetricProbe] = set()
    keys: set[str] = set()
    every_rule_has_metric_key = True
    for rule_type, context_key, rule_config, occurred_at in rows:
        if rule_type != "metric_threshold":
            continue
        probe = metric_probe(context_key, occurred_at)
        if probe is None:
            continue
        probes.add(probe)
        metric_key = metric_key_of(rule_config)
        if metric_key is None:
            every_rule_has_metric_key = False
        else:
            keys.add(metric_key)
    return probes, (keys if every_rule_has_metric_key else None)


async def resolve_metric_entities_at(
    session: AsyncSession,
    probes: Iterable[MetricProbe],
    metric_keys: set[str] | None,
    *,
    lookback: timedelta,
) -> dict[MetricProbe, ResolvedEntity]:
    """``(vcenter_id, entity_moid, occurred_at)`` ごとに、その時点の対象名と種類を返す。

    使うのは ``occurred_at - lookback <= sampled_at <= occurred_at`` のうち最も新しいサンプル（同時刻なら id が
    大きいもの）。``metric_keys`` を渡すとその指標のサンプルだけを見る。範囲にサンプルが無いか、名前が空文字の
    ときは解決しない（戻り値に含めない）。

    等号を含めるのは、評価器（``alert_eval_metric``）が発火・回復の ``fired_at`` / ``resolved_at`` に
    きっかけのサンプルの ``sampled_at`` をそのまま入れ、それが ``occurred_at`` になる（``transition_time``）ため。
    つまり評価器が作ったアラートには、``occurred_at`` ちょうどのサンプルが必ずある。stale は遷移時刻を持たず
    作成時刻になるが、最後のサンプルは鮮度の幅（既定で収集間隔の 3 倍）だけ前なので、さかのぼる幅に収まる。
    このため「``occurred_at`` より後にしかサンプルが無い」のは、評価器を通らずに入った行や保持期間で
    サンプルが消えた行に限られ、「直後の最初のサンプル」で補うことはしない（後の名前を拾うと、改名の後の
    名前が付き、ここで揃えたい「その時点の名前」でなくなる）。

    問い合わせの形（採用）:
        組を ``VALUES`` の CTE（``probes``）にし、組ごとに相関副問い合わせ
        ``SELECT id ... WHERE vcenter_id = ? AND entity_moid = ? [AND metric_key IN (...)]
        AND sampled_at BETWEEN since AND at ORDER BY sampled_at DESC, id DESC LIMIT 1`` で 1 行を選び、
        その id で名前と種類を引く。複合インデックス ``(vcenter_id, entity_moid, metric_key, sampled_at)`` を
        ``metric_key`` ごとに後ろから 1 行読めば済むので、読む量は組の数 × 指標の数にほぼ比例し、
        期間の長さには依存しない（最悪でも組ごとに ``lookback`` の幅の中のサンプルだけ）。
        問い合わせは組 ``IN_CHUNK_SIZE`` 件ごとに 1 本（通知履歴の 1 ページ 200 件なら 1 本）。
        1 本のバインド変数は 5 × 組の数 + 指標の数で、SQLite（3.32 以降 32766）と asyncpg（32767）の上限に収まる。
        SQLite の複合 SELECT の項数の上限（500）は ``VALUES`` には掛からない。
        ``VALUES`` の列の型はモデルの列の型を使う。SQLite では UUID（32 桁の 16 進）と日時を文字列で比べるので、
        保存時と同じ変換をかける必要がある。

    採らなかった形:
        - 期間（またはページ）全体の 1 本の範囲で、範囲の終わりに最も近い名前を使う（以前の形）。名前が表示期間や
          ページの区切りで変わり、通知履歴のリンクで開いたタイムラインから行自身が外れることがあった。
          範囲が広がると読むサンプルも比例して増える。
        - 対象ごとに範囲内の「名前が変わった点」だけを ``LAG`` で取り、Python 側で各アラートの時刻に当てる。
          返す行は少ないが、DB は範囲内のサンプルをすべて読む（期間の長さ × 対象 × 指標。5 分間隔で 90 日なら
          対象・指標ごとに約 26,000 行）。
        - 組を一時テーブルに入れて JOIN する。PostgreSQL ではリクエストごとの ``CREATE TEMP TABLE`` が
          システムカタログを更新し続ける（通知履歴は 30 秒ごとに自動更新する）。
        - PostgreSQL の ``unnest`` に配列で渡す / SQLite の ``json_each`` で渡す。問い合わせは 1 本になるが、
          方言ごとに別の実装が要る。
        - ``alert_history`` と直接相関させる（``context_key`` を SQL で分解する）。方言ごとの文字列操作、
          UUID の表現の違い、日時の演算が要り、旧形式の key も SQL で除く必要があって壊れやすい。

    ``metric_keys`` が None の経路（``metric_key`` を持たないルールが混じるとき）は、インデックスの先頭 2 列
    （vCenter・moid）までしか絞れず、組ごとにその対象のサンプルを指標をまたいで走査し得る。ルールの作成・更新の
    スキーマは ``metric_key`` を必須にしており、評価器も ``metric_key`` の無いルールでは何もしないので、
    この経路は古いデータに限られる。
    """
    ordered = sorted(set(probes), key=lambda p: (str(p[0]), p[1], p[2]))
    if not ordered:
        return {}
    table = MetricSample.__table__.c
    out: dict[MetricProbe, ResolvedEntity] = {}
    for chunk in chunks(ordered, IN_CHUNK_SIZE):
        probe_rows = (
            sql_values(
                column("n", Integer()),
                column("vcenter_id", table.vcenter_id.type),
                column("entity_moid", table.entity_moid.type),
                column("probe_at", table.sampled_at.type),
                column("probe_since", table.sampled_at.type),
                name="probes",
            )
            .data([(n, vid, moid, at, at - lookback) for n, (vid, moid, at) in enumerate(chunk)])
            .cte("probes")
        )
        ms = aliased(MetricSample, name="ms")
        clauses: list[ColumnElement[bool]] = [
            ms.vcenter_id == probe_rows.c.vcenter_id,
            ms.entity_moid == probe_rows.c.entity_moid,
            ms.sampled_at <= probe_rows.c.probe_at,
            ms.sampled_at >= probe_rows.c.probe_since,
        ]
        if metric_keys:
            clauses.append(ms.metric_key.in_(sorted(metric_keys)))
        sample_id = (
            select(ms.id)
            .where(*clauses)
            .order_by(ms.sampled_at.desc(), ms.id.desc())
            .limit(1)
            .correlate(probe_rows)
            .scalar_subquery()
        )
        picked = select(probe_rows.c.n.label("n"), sample_id.label("sample_id")).subquery("picked")
        stmt = select(picked.c.n, MetricSample.entity_name, MetricSample.entity_type).join(
            MetricSample, MetricSample.id == picked.c.sample_id
        )
        for n, name, etype in (await session.execute(stmt)).all():
            if name:
                out[chunk[int(n)]] = ResolvedEntity(name=name, entity_type=etype or None)
    return out
