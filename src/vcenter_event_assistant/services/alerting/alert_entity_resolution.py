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



# 名前を引く 1 件の問い合わせ: (vcenter_id, entity_moid, そのルールの metric_key（無ければ None）,
# アラートの occurred_at（UTC）)。アラート 1 件の名前は、この 4 つだけで決まる。
MetricProbe = tuple[uuid.UUID, str, str | None, datetime]


def metric_probe(context_key: str, rule_config: Any, occurred_at: datetime) -> MetricProbe | None:
    """metric_threshold のアラートから、名前を引く組を作る。旧形式の key は None。

    指標はそのアラートのルール自身の ``config["metric_key"]`` だけを使う。同じ呼び出しに居合わせるほかの
    アラートのルールの指標は混ぜない（混ぜると、ページや表示期間ごとに名前が変わる）。
    """
    parsed = parse_metric_context_key(context_key)
    if parsed is None:
        return None
    return parsed[0], parsed[1], metric_key_of(rule_config), to_utc(occurred_at)


def collect_metric_probes(rows: Iterable[tuple[str, str, Any, datetime]]) -> set[MetricProbe]:
    """``(rule_type, context_key, rule_config, occurred_at)`` の列から、名前を引く組を重複を除いて求める。"""
    probes: set[MetricProbe] = set()
    for rule_type, context_key, rule_config, occurred_at in rows:
        if rule_type != "metric_threshold":
            continue
        probe = metric_probe(context_key, rule_config, occurred_at)
        if probe is not None:
            probes.add(probe)
    return probes


async def resolve_metric_entities_at(
    session: AsyncSession,
    probes: Iterable[MetricProbe],
    *,
    lookback: timedelta,
) -> dict[MetricProbe, ResolvedEntity]:
    """``(vcenter_id, entity_moid, metric_key, occurred_at)`` ごとに、その時点の対象名と種類を返す。

    使うのは、その指標の ``occurred_at - lookback <= sampled_at <= occurred_at`` のうち最も新しいサンプル。
    ``metric_key`` が None の組（ルールに ``metric_key`` が無い古いデータ）だけは指標で絞らず、全指標から
    最も新しいもの（同時刻なら id が大きいもの）を使う。範囲にサンプルが無いか、名前が空文字のときは解決しない
    （戻り値に含めない）。各組の結果はその組だけで決まり、同じ呼び出しのほかの組には依存しない。そのため
    同じアラートは、通知履歴でもタイムラインでも、どのページ・どの表示期間で引いても同じ名前になる。

    指標をそのルール自身のものに限る理由（「常に全指標から引く」を採らなかった理由）:
        - 評価器（``alert_eval_metric``）はルールの指標のサンプルだけを見て、発火・回復の ``fired_at`` /
          ``resolved_at`` にきっかけのサンプルの ``sampled_at`` をそのまま入れ、それが ``occurred_at`` になる
          （``transition_time``）。ルール自身の指標で引けば、評価器が判断に使ったそのサンプル（通知の本文に
          出した名前）がちょうど当たる。
        - インデックス ``(vcenter_id, entity_moid, metric_key, sampled_at)`` の 4 列すべてが等号と範囲で効き、
          組ごとに後ろから 1 行読めば止まる（一意制約 ``uq_metric_sample_point`` により、同じ 4 列の値の行は
          1 つなので id での並べ替えも要らない）。全指標から引くと先頭 2 列までしか絞れず、方言ごとに別の
          インデックス（SQLite は ``sampled_at`` の単独インデックス）を後ろから読んでほかの対象の行も読み飛ばす。
        - stale のアラートは遷移時刻を持たず作成時刻が ``occurred_at`` になるので、ルールの指標の最後のサンプルは
          鮮度の幅（既定で収集間隔の 3 倍）だけ前になる。その間にほかの指標のサンプルで改名が見えていても、
          stale の行には改名前の名前が付き得る。ただしその行が出ている間はどの画面でも同じ名前なので、リンクの
          絞り込みからは外れない（全指標から引くと改名後の名前になるが、ここで守りたい一貫性はどちらでも保てる）。

    等号を含めるのは上のとおり、評価器が作ったアラートには ``occurred_at`` ちょうどのサンプルが必ずあるため。
    stale も最後のサンプルはさかのぼる幅に収まる。このため「``occurred_at`` より後にしかサンプルが無い」のは、
    評価器を通らずに入った行や保持期間でサンプルが消えた行に限られ、「直後の最初のサンプル」で補うことはしない
    （後の名前を拾うと、改名の後の名前が付き、ここで揃えたい「その時点の名前」でなくなる）。

    問い合わせの形（採用）:
        組を ``VALUES`` の CTE（``probes``）にし、組ごとに相関副問い合わせ
        ``SELECT id ... WHERE vcenter_id = ? AND entity_moid = ? AND metric_key = ?
        AND sampled_at BETWEEN since AND at ORDER BY sampled_at DESC LIMIT 1`` で 1 行を選び、その id で
        名前と種類を引く。読む量は組の数にほぼ比例し（組ごとに 1 行）、期間の長さには依存しない。
        ``metric_key`` が None の組は、指標の条件を外し ``ORDER BY sampled_at DESC, id DESC`` にした別の
        問い合わせにする（1 本の中で ``metric_key = ? OR ? IS NULL`` とするとインデックスの 3 列目が効かなくなる）。
        問い合わせは、指標のある組・無い組それぞれ ``IN_CHUNK_SIZE`` 件ごとに 1 本（通知履歴の 1 ページ 200 件なら、
        古いデータが混じらなければ 1 本）。1 本のバインド変数は 6 × 組の数で、SQLite（3.32 以降 32766）と
        asyncpg（32767）の上限に収まる。SQLite の複合 SELECT の項数の上限（500）は ``VALUES`` には掛からない。
        ``VALUES`` の列の型はモデルの列の型を使う。SQLite では UUID（32 桁の 16 進）と日時を文字列で比べるので、
        保存時と同じ変換をかける必要がある。

    採らなかった形:
        - 期間（またはページ）全体の 1 本の範囲で、範囲の終わりに最も近い名前を使う（以前の形）。名前が表示期間や
          ページの区切りで変わり、通知履歴のリンクで開いたタイムラインから行自身が外れることがあった。
          範囲が広がると読むサンプルも比例して増える。
        - 呼び出しに含まれる全ルールの指標の和集合で絞る（以前の形）。居合わせるアラートで名前が変わる。
        - 対象ごとに範囲内の「名前が変わった点」だけを ``LAG`` で取り、Python 側で各アラートの時刻に当てる。
          返す行は少ないが、DB は範囲内のサンプルをすべて読む（期間の長さ × 対象 × 指標。5 分間隔で 90 日なら
          対象・指標ごとに約 26,000 行）。
        - 組を一時テーブルに入れて JOIN する。PostgreSQL ではリクエストごとの ``CREATE TEMP TABLE`` が
          システムカタログを更新し続ける（通知履歴は 30 秒ごとに自動更新する）。
        - PostgreSQL の ``unnest`` に配列で渡す / SQLite の ``json_each`` で渡す。問い合わせは 1 本になるが、
          方言ごとに別の実装が要る。
        - ``alert_history`` と直接相関させる（``context_key`` を SQL で分解する）。方言ごとの文字列操作、
          UUID の表現の違い、日時の演算が要り、旧形式の key も SQL で除く必要があって壊れやすい。

    ``metric_key`` が None の組は、インデックスの先頭 2 列（vCenter・moid）までしか絞れない。ルールの作成・更新の
    スキーマは ``metric_key`` を必須にしており、評価器も ``metric_key`` の無いルールでは何もしないので、
    この経路は古いデータに限られる。
    """
    unique = set(probes)
    out: dict[MetricProbe, ResolvedEntity] = {}
    for with_key in (True, False):
        group = sorted(
            (p for p in unique if (p[2] is not None) == with_key),
            key=lambda p: (str(p[0]), p[1], p[2] or "", p[3]),
        )
        for chunk in chunks(group, IN_CHUNK_SIZE):
            out.update(await _resolve_chunk(session, chunk, lookback=lookback, with_key=with_key))
    return out


async def _resolve_chunk(
    session: AsyncSession,
    chunk: Sequence[MetricProbe],
    *,
    lookback: timedelta,
    with_key: bool,
) -> dict[MetricProbe, ResolvedEntity]:
    """``resolve_metric_entities_at`` の 1 本分。``with_key`` が真なら組の指標で絞り、偽なら絞らない。"""
    table = MetricSample.__table__.c
    probe_rows = (
        sql_values(
            column("n", Integer()),
            column("vcenter_id", table.vcenter_id.type),
            column("entity_moid", table.entity_moid.type),
            column("metric_key", table.metric_key.type),
            column("probe_at", table.sampled_at.type),
            column("probe_since", table.sampled_at.type),
            name="probes",
        )
        .data(
            [
                (n, vid, moid, key or "", at, at - lookback)
                for n, (vid, moid, key, at) in enumerate(chunk)
            ]
        )
        .cte("probes")
    )
    ms = aliased(MetricSample, name="ms")
    clauses: list[ColumnElement[bool]] = [
        ms.vcenter_id == probe_rows.c.vcenter_id,
        ms.entity_moid == probe_rows.c.entity_moid,
        ms.sampled_at <= probe_rows.c.probe_at,
        ms.sampled_at >= probe_rows.c.probe_since,
    ]
    if with_key:
        clauses.append(ms.metric_key == probe_rows.c.metric_key)
        # 4 列の値が同じ行は一意制約で 1 つなので、sampled_at だけで並びが決まる（インデックスの順のまま止まる）。
        order = (ms.sampled_at.desc(),)
    else:
        order = (ms.sampled_at.desc(), ms.id.desc())
    sample_id = (
        select(ms.id)
        .where(*clauses)
        .order_by(*order)
        .limit(1)
        .correlate(probe_rows)
        .scalar_subquery()
    )
    picked = select(probe_rows.c.n.label("n"), sample_id.label("sample_id")).subquery("picked")
    stmt = select(picked.c.n, MetricSample.entity_name, MetricSample.entity_type).join(
        MetricSample, MetricSample.id == picked.c.sample_id
    )
    out: dict[MetricProbe, ResolvedEntity] = {}
    for n, name, etype in (await session.execute(stmt)).all():
        if name:
            out[chunk[int(n)]] = ResolvedEntity(name=name, entity_type=etype or None)
    return out
