"""タイムライン画面専用 API（``POST /api/incident-timeline/view``）のサービス。

構成:

- 入口 ``build_incident_timeline_view``: 期間を秒に揃え、同時実行数の枠を取り、例外を HTTP に変換する。
- 種別ごとの収集関数（``_collect_events`` / ``_collect_alerts``）: DB から読み、``TimelineEntry`` の列と
  俯瞰グラフの件数を返す。種別を足すときは収集関数を書いて ``_COLLECTORS`` に登録する
  （PR4 で ``metric`` → ``metric_breach``、``log`` → ``log_error`` を足す）。
- 純粋関数（DB を使わない）: バケット幅の選択、level の算出、並べ替え、連続のまとめ、打ち切り、ハイライト。

チャットの LLM 用集計（``services/chat/``）とは独立しており、その挙動には影響しない。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.schemas.incident_timeline_view import (
    IncidentTimelineHighlights,
    IncidentTimelineItemRef,
    IncidentTimelineNewEventType,
    IncidentTimelineOverviewBucket,
    IncidentTimelineTopEntity,
    IncidentTimelineViewItem,
    IncidentTimelineViewRequest,
    IncidentTimelineViewResponse,
    TimelineLevel,
    TimelineSource,
)
from vcenter_event_assistant.db.models import AlertHistory, AlertRule, EventRecord, MetricSample, VCenter
from vcenter_event_assistant.services.alerting.alert_eval_common import is_vcenter_scoped_context_key
from vcenter_event_assistant.services.chat.aggregation_limiter import (
    AggregationBusy,
    AggregationLimitExceeded,
    aggregation_slot,
)
from vcenter_event_assistant.services.sql_like import contains_case_insensitive
from vcenter_event_assistant.services.sql_time import bucket_index_expr, truncate_to_second
from vcenter_event_assistant.settings_binding import require_settings

# 同時実行数の上限に達したときに、再試行までの目安として返す秒数（chat_context_payloads と同じ値）。
_BUSY_RETRY_AFTER_SECONDS = 5

# 俯瞰グラフのバケット幅の候補（秒）。棒の数が _MAX_OVERVIEW_BUCKETS 以下になる最小の幅を選ぶ。
# 隣り合う候補の比は 2.5 倍以下なので棒は 48 本以上になる。例外は 30 分〜1 時間の期間で、1 分未満の幅を
# 使わないため 30〜60 本になる（choose_bucket_seconds 参照）。
_NICE_BUCKET_SECONDS: tuple[int, ...] = (
    1, 2, 5, 10, 15, 30,
    60, 120, 300, 600, 900, 1800,
    3600, 2 * 3600, 3 * 3600, 6 * 3600, 12 * 3600, 86400,
)
_MAX_OVERVIEW_BUCKETS = 120

_TOP_ENTITIES_LIMIT = 5
_NEW_EVENT_TYPES_LIMIT = 10
# IN に並べる値の数の上限（SQLite / asyncpg のバインド変数の上限に当たらないよう分割する）。
_IN_CHUNK_SIZE = 500

OVERVIEW_FIELDS: tuple[str, ...] = ("event_total", "event_notable", "alert", "metric_breach", "log_error")

_LEVEL_RANK: dict[str, int] = {"info": 0, "warning": 1, "error": 2, "critical": 3}
_LEVEL_BY_RANK: dict[int, TimelineLevel] = {0: "info", 1: "warning", 2: "error", 3: "critical"}
# 同じ時刻の項目の並び（小さいほど先）。PR4 で metric / log を足す。
_KIND_ORDER: dict[str, int] = {"alert": 0, "event": 1, "metric": 2, "log": 3}

_ERROR_SEVERITIES = frozenset({"error", "critical", "fatal"})
_WARNING_SEVERITIES = frozenset({"warning", "warn"})
_ALERT_LEVELS: frozenset[str] = frozenset({"critical", "error", "warning"})


# --- 内部表現 ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """時系列リストの 1 項目の内部表現。

    件数が多くなり得る（最大 ``context_aggregation_max_rows`` 行）ので、Pydantic のモデルは
    返す項目にだけ作る（``to_item``）。

    - ``source_id``: 元レコードの id。同時刻の並びと ``id``（``{kind}:{source_id}``）に使う。
    - ``merge_key``: 隣り合う項目でこの値が等しいとき 1 件にまとめる。None はまとめない。
    - ``ref``: ``IncidentTimelineItemRef`` のフィールド名と値。
    """

    kind: TimelineSource
    source_id: int
    timestamp_utc: datetime
    level: TimelineLevel
    title: str
    detail: str | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    vcenter_id: uuid.UUID | None = None
    vcenter_name: str | None = None
    score: int | None = None
    count: int = 1
    end_utc: datetime | None = None
    merge_key: tuple[Any, ...] | None = None
    ref: Mapping[str, Any] = field(default_factory=dict)

    @property
    def item_id(self) -> str:
        return f"{self.kind}:{self.source_id}"

    def to_item(self) -> IncidentTimelineViewItem:
        return IncidentTimelineViewItem(
            id=self.item_id,
            kind=self.kind,
            timestamp_utc=self.timestamp_utc,
            end_utc=self.end_utc,
            level=self.level,
            title=self.title,
            detail=self.detail,
            entity_name=self.entity_name,
            entity_type=self.entity_type,
            vcenter_id=self.vcenter_id,
            vcenter_name=self.vcenter_name,
            score=self.score,
            count=self.count,
            ref=IncidentTimelineItemRef(**dict(self.ref)),
        )


@dataclass(frozen=True, slots=True)
class EventTypeStats:
    """今回の期間に出たイベント種別ごとの集計（``new_event_types`` の候補）。"""

    event_type: str
    count: int
    first_seen_utc: datetime
    max_score: int


@dataclass(frozen=True, slots=True)
class _Scope:
    """収集関数が共通で使う条件。"""

    from_utc: datetime
    to_utc: datetime
    vcenter_id: uuid.UUID | None
    entity: str | None
    min_score: int
    bucket_sec: int
    bucket_count: int
    max_rows: int
    dialect_name: str


@dataclass
class _Collected:
    entries: list[TimelineEntry] = field(default_factory=list)
    # OVERVIEW_FIELDS のいずれか -> バケットごとの件数（長さは bucket_count）
    overview: dict[str, list[int]] = field(default_factory=dict)


# --- 純粋関数: バケット -----------------------------------------------------------------


def choose_bucket_seconds(
    from_utc: datetime,
    to_utc: datetime,
    *,
    max_buckets: int = _MAX_OVERVIEW_BUCKETS,
) -> int:
    """俯瞰グラフのバケット幅（秒）。棒が ``max_buckets`` 本以下になる最小の「きりのよい」幅。

    チャット用の ``compute_chat_bucket_seconds`` は 6 時間以下を一律 15 分幅にする（最大 48 本）ため、
    既定の 1〜2 時間の期間では棒が 4〜8 本しかなく、初動調査の俯瞰には粗すぎる。そのためこの API 用に
    30〜120 本程度に収まる幅を選ぶ関数を別に持つ。

    30 分以上の期間では 1 分未満の幅を使わない（1 時間を 30 秒幅 120 本にするより、1 分幅 60 本のほうが
    件数を読みやすい）。30 分未満でだけ 1 分未満の幅にして、棒が少なくなりすぎないようにする。
    """
    dur = int((to_utc - from_utc).total_seconds())
    if dur < 1:
        raise ValueError("from_utc must be at least 1 second before to_utc")
    min_width = 60 if dur >= 30 * 60 else 1
    for width in _NICE_BUCKET_SECONDS:
        if width >= min_width and _ceil_div(dur, width) <= max_buckets:
            return width
    # 候補に収まらない長さ（スキーマ上は 90 日までなので通常は来ない）は日単位で切り上げる。
    day = 86400
    return _ceil_div(dur, max_buckets * day) * day


def overview_bucket_count(from_utc: datetime, to_utc: datetime, bucket_sec: int) -> int:
    """``from`` から ``to`` までを隙間なく埋めるバケット数。割り切れないときは最後のバケットが ``to`` をはみ出す。"""
    dur = int((to_utc - from_utc).total_seconds())
    return max(1, _ceil_div(dur, bucket_sec))


def bucket_index(ts: datetime, from_utc: datetime, bucket_sec: int) -> int:
    """DB 側の ``bucket_index_expr`` と同じく、秒に切り捨ててからバケット番号を求める。"""
    return int((truncate_to_second(ts) - from_utc).total_seconds()) // bucket_sec


def count_per_bucket(
    timestamps: Iterable[datetime],
    from_utc: datetime,
    bucket_sec: int,
    bucket_count: int,
) -> list[int]:
    """時刻の列をバケットごとの件数にする。範囲外（``[from, from + bucket_count * bucket_sec)`` の外）は数えない。"""
    counts = [0] * bucket_count
    for ts in timestamps:
        idx = bucket_index(ts, from_utc, bucket_sec)
        if 0 <= idx < bucket_count:
            counts[idx] += 1
    return counts


def build_overview(
    from_utc: datetime,
    bucket_sec: int,
    bucket_count: int,
    counts: Mapping[str, Sequence[int]],
) -> list[IncidentTimelineOverviewBucket]:
    """件数 0 のバケットも含めて等幅の俯瞰を作る。``counts`` に無い種別は 0。"""
    out: list[IncidentTimelineOverviewBucket] = []
    for idx in range(bucket_count):
        values = {name: int(counts[name][idx]) if name in counts else 0 for name in OVERVIEW_FIELDS}
        out.append(
            IncidentTimelineOverviewBucket(
                bucket_start_utc=from_utc + timedelta(seconds=idx * bucket_sec),
                **values,
            )
        )
    return out


# --- 純粋関数: level・タイトル ----------------------------------------------------------


def event_level(score: int | None, severity: str | None) -> TimelineLevel:
    """notable_score から level を決め、severity が error / warning 相当ならそれを下限にする。"""
    s = int(score or 0)
    if s >= 80:
        rank = 3
    elif s >= 60:
        rank = 2
    elif s >= 40:
        rank = 1
    else:
        rank = 0
    sev = (severity or "").strip().lower()
    if sev in _ERROR_SEVERITIES:
        rank = max(rank, 2)
    elif sev in _WARNING_SEVERITIES:
        rank = max(rank, 1)
    return _LEVEL_BY_RANK[rank]


def alert_level(value: str | None) -> TimelineLevel:
    """履歴の ``alert_level`` をそのまま使う。想定外の値は warning。"""
    v = (value or "").strip().lower()
    return v if v in _ALERT_LEVELS else "warning"  # type: ignore[return-value]


def alert_title(rule_name: str, state: str | None) -> str:
    """ルール名と状態が分かる短い文。状態の語は通知履歴の画面（AlertHistoryPanel）の表記に合わせる。

    画面は firing を「発火中」、stale を「データ古い」、それ以外をすべて「回復済み」と表示する。
    """
    if state == "firing":
        return f"{rule_name} が発火"
    if state == "stale":
        return f"{rule_name} のデータが古い"
    return f"{rule_name} が回復"


def entity_matches(entity_name: str | None, needle: str) -> bool:
    """SQL 側の ``contains_case_insensitive`` と同じく、大文字小文字を区別しない部分一致。"""
    if not entity_name:
        return False
    return needle.lower() in entity_name.lower()


# --- 純粋関数: 並べ替え・まとめ・打ち切り -----------------------------------------------


def entry_sort_key(entry: TimelineEntry) -> tuple[datetime, int, int]:
    """時刻の昇順、同時刻は alert → event の順、その中は元レコードの id の昇順。"""
    return (entry.timestamp_utc, _KIND_ORDER.get(entry.kind, len(_KIND_ORDER)), entry.source_id)


def sort_entries(entries: Iterable[TimelineEntry]) -> list[TimelineEntry]:
    return sorted(entries, key=entry_sort_key)


def merge_consecutive(entries: Sequence[TimelineEntry]) -> list[TimelineEntry]:
    """時刻順に並んだ列で、``merge_key`` が等しい項目が隣り合うときだけ 1 件にまとめる。

    まとめた項目は、時刻・id・参照・タイトル・詳細は最初のもの、``end_utc`` は最後の時刻、
    ``count`` は件数の合計、``score`` は最大、``level`` は最も重いものになる。
    """
    out: list[TimelineEntry] = []
    for entry in entries:
        prev = out[-1] if out else None
        if prev is not None and prev.merge_key is not None and prev.merge_key == entry.merge_key:
            out[-1] = _merge_pair(prev, entry)
        else:
            out.append(entry)
    return out


def _merge_pair(first: TimelineEntry, nxt: TimelineEntry) -> TimelineEntry:
    if first.score is None:
        score = nxt.score
    elif nxt.score is None:
        score = first.score
    else:
        score = max(first.score, nxt.score)
    level = first.level if _LEVEL_RANK[first.level] >= _LEVEL_RANK[nxt.level] else nxt.level
    return replace(
        first,
        count=first.count + nxt.count,
        end_utc=nxt.end_utc or nxt.timestamp_utc,
        score=score,
        level=level,
    )


def select_within_limit(
    entries: Sequence[TimelineEntry],
    limit: int,
    anchor: datetime | None,
) -> tuple[list[TimelineEntry], bool]:
    """``limit`` 件を超えたら残す項目を選ぶ。戻り値は（時刻の昇順の列, 打ち切ったか）。

    ``entries`` は ``sort_entries`` の順（まとめた後）を前提にする。優先順位:

    - ``anchor`` あり: ``|timestamp_utc - anchor|`` が小さい順
    - ``anchor`` なし: level が重い順 → score が高い順 → 新しい順

    ``anchor`` ありで距離が同じときも、続けて level → score → 新しい順で比べる。それでも同じなら
    入力の並び（時刻・種別・元 id）で決めるので、結果は常に決定的になる。
    """
    if len(entries) <= limit:
        return list(entries), False

    def priority(indexed: tuple[int, TimelineEntry]) -> tuple[float, ...]:
        idx, e = indexed
        tail = (
            -_LEVEL_RANK[e.level],
            -(e.score if e.score is not None else -1),
            -e.timestamp_utc.timestamp(),
            idx,
        )
        if anchor is None:
            return tail
        return (abs((e.timestamp_utc - anchor).total_seconds()), *tail)

    chosen = sorted(enumerate(entries), key=priority)[:limit]
    chosen.sort(key=lambda pair: pair[0])
    return [e for _, e in chosen], True


# --- 純粋関数: ハイライト ---------------------------------------------------------------


def first_signal(entries: Sequence[TimelineEntry]) -> TimelineEntry | None:
    """level が warning 以上で最も早い項目（``entries`` は時刻順）。"""
    for e in entries:
        if _LEVEL_RANK[e.level] >= _LEVEL_RANK["warning"]:
            return e
    return None


def top_entities(
    entries: Sequence[TimelineEntry],
    *,
    limit: int = _TOP_ENTITIES_LIMIT,
) -> list[IncidentTimelineTopEntity]:
    """``entity_name`` ごとに ``count``（まとめる前の件数）を合計し、多い順に上位を返す。

    同数なら最初に現れた時刻が早い順、それも同じなら名前の順。レスポンスに vCenter の欄が無いので、
    vCenter が違っても同じ名前の対象は 1 つに数える（画面の「この対象で絞る」も名前で絞る）。
    ``entity_type`` は最初に分かった値を使う。
    """
    acc: dict[str, list[Any]] = {}
    for e in entries:
        if not e.entity_name:
            continue
        slot = acc.get(e.entity_name)
        if slot is None:
            acc[e.entity_name] = [e.count, e.timestamp_utc, e.entity_type]
            continue
        slot[0] += e.count
        if e.timestamp_utc < slot[1]:
            slot[1] = e.timestamp_utc
        if slot[2] is None and e.entity_type:
            slot[2] = e.entity_type
    ranked = sorted(acc.items(), key=lambda kv: (-kv[1][0], kv[1][1], kv[0]))[:limit]
    return [
        IncidentTimelineTopEntity(
            entity_name=name,
            entity_type=etype,
            item_count=count,
            first_seen_utc=first_seen,
        )
        for name, (count, first_seen, etype) in ranked
    ]


def summarize_event_types(entries: Iterable[TimelineEntry]) -> dict[str, EventTypeStats]:
    """まとめる前のイベント項目から、種別ごとの件数・最初の時刻・最大スコアを求める。"""
    acc: dict[str, list[Any]] = {}
    for e in entries:
        if e.kind != "event":
            continue
        event_type = e.ref.get("event_type")
        if not event_type:
            continue
        score = int(e.score or 0)
        slot = acc.get(event_type)
        if slot is None:
            acc[event_type] = [e.count, e.timestamp_utc, score]
            continue
        slot[0] += e.count
        if e.timestamp_utc < slot[1]:
            slot[1] = e.timestamp_utc
        slot[2] = max(slot[2], score)
    return {
        et: EventTypeStats(event_type=et, count=c, first_seen_utc=fs, max_score=ms)
        for et, (c, fs, ms) in acc.items()
    }


def pick_new_event_types(
    stats: Mapping[str, EventTypeStats],
    seen_before: Iterable[str],
    *,
    limit: int = _NEW_EVENT_TYPES_LIMIT,
) -> list[IncidentTimelineNewEventType]:
    """直前の期間に無かった種別を、最大スコアの降順 → 最初の時刻の昇順 → 種別名の順で返す。"""
    seen = set(seen_before)
    fresh = [s for s in stats.values() if s.event_type not in seen]
    fresh.sort(key=lambda s: (-s.max_score, s.first_seen_utc, s.event_type))
    return [
        IncidentTimelineNewEventType(
            event_type=s.event_type,
            count=s.count,
            first_seen_utc=s.first_seen_utc,
            max_score=s.max_score,
        )
        for s in fresh[:limit]
    ]


# --- 入口 -------------------------------------------------------------------------------


async def build_incident_timeline_view(
    session: AsyncSession,
    body: IncidentTimelineViewRequest,
    *,
    owner_key: str,
) -> IncidentTimelineViewResponse:
    """期間内のイベントとアラートを、個々の出来事として時刻順に返す。

    ``owner_key`` は同時実行数の上限（``aggregation_slot``）を利用者ごとに数えるための識別子。
    PR1 では ``event`` と ``alert`` だけを扱い、``metric`` と ``log`` は後の PR で足す。
    """
    # DB 側の時間バケットは秒単位なので、期間は入口で 1 回だけ秒に揃え、以降すべてで同じ値を使う。
    ft = truncate_to_second(to_utc(body.from_time))
    tt = truncate_to_second(to_utc(body.to_time))
    if ft >= tt:
        raise HTTPException(
            status_code=400,
            detail="from は to より前である必要があります",
        )

    # サービス層なので bind 済みの Settings を直接読む（ルートの Depends(get_app_settings) の差し替えは効かない）。
    settings = require_settings()
    try:
        with aggregation_slot(
            owner_key,
            global_limit=settings.context_aggregation_concurrency,
            per_owner_limit=settings.context_aggregation_concurrency_per_user,
        ):
            return await _build_in_slot(
                session,
                body,
                ft,
                tt,
                max_rows=settings.context_aggregation_max_rows,
            )
    except AggregationBusy:
        raise HTTPException(
            status_code=503,
            detail="集計の処理が混み合っています。しばらく待ってから再度お試しください。",
            headers={"Retry-After": str(_BUSY_RETRY_AFTER_SECONDS)},
        ) from None
    except AggregationLimitExceeded:
        raise HTTPException(
            status_code=422,
            detail=(
                "対象の出来事が多すぎて集計できません。"
                "期間を短くするか、vCenter を指定して絞り込んでください。"
            ),
        ) from None


async def _build_in_slot(
    session: AsyncSession,
    body: IncidentTimelineViewRequest,
    ft: datetime,
    tt: datetime,
    *,
    max_rows: int,
) -> IncidentTimelineViewResponse:
    bucket_sec = choose_bucket_seconds(ft, tt)
    n_buckets = overview_bucket_count(ft, tt, bucket_sec)
    bind = session.get_bind()
    scope = _Scope(
        from_utc=ft,
        to_utc=tt,
        vcenter_id=body.vcenter_id,
        entity=body.entity,
        min_score=body.min_score,
        bucket_sec=bucket_sec,
        bucket_count=n_buckets,
        max_rows=max_rows,
        dialect_name=bind.dialect.name if bind is not None else "sqlite",
    )

    entries: list[TimelineEntry] = []
    overview_counts: dict[str, list[int]] = {}
    requested = set(body.sources)
    for source, collector in _COLLECTORS.items():
        if source not in requested:
            continue
        collected = await collector(session, scope)
        entries.extend(collected.entries)
        overview_counts.update(collected.overview)

    new_types: list[IncidentTimelineNewEventType] = []
    stats = summarize_event_types(entries)
    if stats:
        seen = await _event_types_seen_in_previous_period(session, scope, stats.keys())
        new_types = pick_new_event_types(stats, seen)

    entries = await _attach_vcenter_names(session, entries)
    merged = merge_consecutive(sort_entries(entries))
    anchor = to_utc(body.anchor_time) if body.anchor_time is not None else None
    kept, truncated = select_within_limit(merged, body.item_limit, anchor)
    signal = first_signal(merged)

    return IncidentTimelineViewResponse(
        from_utc=ft,
        to_utc=tt,
        anchor_utc=anchor,
        bucket_seconds=bucket_sec,
        overview=build_overview(ft, bucket_sec, n_buckets, overview_counts),
        items=[e.to_item() for e in kept],
        truncated=truncated,
        total_items=len(merged),
        highlights=IncidentTimelineHighlights(
            first_signal=signal.to_item() if signal is not None else None,
            top_entities=top_entities(merged),
            new_event_types=new_types,
        ),
    )


# --- 収集: イベント ---------------------------------------------------------------------


def _event_filters(
    from_utc: datetime,
    to_utc: datetime,
    *,
    vcenter_id: uuid.UUID | None,
    entity: str | None,
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = [
        EventRecord.occurred_at >= from_utc,
        EventRecord.occurred_at < to_utc,
    ]
    if vcenter_id is not None:
        clauses.append(EventRecord.vcenter_id == vcenter_id)
    if entity:
        clauses.append(contains_case_insensitive(EventRecord.entity_name, entity))
    return clauses


async def _collect_events(session: AsyncSession, scope: _Scope) -> _Collected:
    """``event_total`` / ``event_notable`` の俯瞰（DB 側の GROUP BY）と、``min_score`` 以上の個別イベント。"""
    filters = _event_filters(
        scope.from_utc, scope.to_utc, vcenter_id=scope.vcenter_id, entity=scope.entity
    )

    # PostgreSQL では同じ式でも SELECT と GROUP BY で別のバインド変数になるため、バケット番号は
    # 副問い合わせの列にしてから集計する（sql_time.py の注意書き）。
    base = (
        select(
            bucket_index_expr(
                EventRecord.occurred_at,
                scope.dialect_name,
                from_epoch=int(scope.from_utc.timestamp()),
                bucket_sec=scope.bucket_sec,
            ).label("bidx"),
            EventRecord.notable_score.label("score"),
        )
        .where(and_(*filters))
        .subquery("base")
    )
    overview_stmt = select(
        base.c.bidx,
        func.count().label("total"),
        func.sum(case((base.c.score >= scope.min_score, 1), else_=0)).label("notable"),
    ).group_by(base.c.bidx)
    totals = [0] * scope.bucket_count
    notables = [0] * scope.bucket_count
    for bidx, total, notable in (await session.execute(overview_stmt)).all():
        idx = int(bidx)
        if 0 <= idx < scope.bucket_count:
            totals[idx] = int(total or 0)
            notables[idx] = int(notable or 0)

    # まとめ・打ち切り・ハイライトを正しく出すため、条件に合う行はすべて読む。読み過ぎを防ぐ上限を
    # 超えたら、黙って切らずに 422 にする（total_items と truncated が嘘にならないように）。
    list_stmt = (
        select(
            EventRecord.id,
            EventRecord.occurred_at,
            EventRecord.event_type,
            EventRecord.message,
            EventRecord.severity,
            EventRecord.entity_name,
            EventRecord.entity_type,
            EventRecord.vcenter_id,
            EventRecord.notable_score,
        )
        .where(*filters, EventRecord.notable_score >= scope.min_score)
        .order_by(EventRecord.occurred_at, EventRecord.id)
        .limit(scope.max_rows + 1)
    )
    rows = (await session.execute(list_stmt)).all()
    if len(rows) > scope.max_rows:
        raise AggregationLimitExceeded("incident_timeline_view.events", scope.max_rows)

    entries = [
        TimelineEntry(
            kind="event",
            source_id=int(row.id),
            timestamp_utc=to_utc(row.occurred_at),
            level=event_level(row.notable_score, row.severity),
            title=row.event_type,
            detail=row.message or None,
            entity_name=row.entity_name,
            entity_type=row.entity_type,
            vcenter_id=row.vcenter_id,
            score=int(row.notable_score),
            merge_key=("event", row.event_type, row.entity_name, row.vcenter_id),
            ref={"event_id": int(row.id), "event_type": row.event_type},
        )
        for row in rows
    ]
    return _Collected(entries=entries, overview={"event_total": totals, "event_notable": notables})


async def _event_types_seen_in_previous_period(
    session: AsyncSession,
    scope: _Scope,
    event_types: Iterable[str],
) -> set[str]:
    """直前の同じ長さの期間に（スコアに関係なく）1 件でもあった種別。DB 側の GROUP BY で求める。"""
    prev_from = scope.from_utc - (scope.to_utc - scope.from_utc)
    filters = _event_filters(
        prev_from, scope.from_utc, vcenter_id=scope.vcenter_id, entity=scope.entity
    )
    seen: set[str] = set()
    for chunk in _chunks(sorted(event_types), _IN_CHUNK_SIZE):
        stmt = (
            select(EventRecord.event_type)
            .where(*filters, EventRecord.event_type.in_(chunk))
            .group_by(EventRecord.event_type)
        )
        seen.update(str(v) for v in (await session.execute(stmt)).scalars().all())
    return seen


# --- 収集: アラート ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ResolvedEntity:
    name: str
    entity_type: str | None


async def _collect_alerts(session: AsyncSession, scope: _Scope) -> _Collected:
    """``AlertHistory`` を ``notified_at`` で期間に絞り、対象を解決して項目にする。

    - ``metric_threshold``: ``context_key``（``{vcenter_id}:{entity_moid}``）から vCenter と moid を取り出し、
      ``MetricSample`` の最新の名前・種類で対象を解決する。旧形式（moid だけ）の key は vCenter が分からず、
      moid は vCenter をまたいで重複し得るので、誤った対象に紐付けないよう名前は解決しない。
    - ``event_score``: ``context_key`` はイベント種別。対象と vCenter は持たない。
    - vCenter の絞り込みでは、vCenter を特定できないアラートは全 vCenter にまたがる情報として残す。
    - 対象の絞り込みでは、対象名が一致するアラートだけを残す。
    """
    stmt = (
        select(
            AlertHistory.id,
            AlertHistory.notified_at,
            AlertHistory.alert_level,
            AlertHistory.state,
            AlertHistory.context_key,
            AlertHistory.rule_id,
            AlertRule.name.label("rule_name"),
            AlertRule.rule_type,
            AlertRule.config.label("rule_config"),
        )
        .join(AlertRule, AlertRule.id == AlertHistory.rule_id)
        .where(
            AlertHistory.notified_at >= scope.from_utc,
            AlertHistory.notified_at < scope.to_utc,
        )
        .order_by(AlertHistory.notified_at, AlertHistory.id)
        .limit(scope.max_rows + 1)
    )
    rows = (await session.execute(stmt)).all()
    if len(rows) > scope.max_rows:
        raise AggregationLimitExceeded("incident_timeline_view.alerts", scope.max_rows)

    # metric_threshold の対象を 1 本の SQL でまとめて解決する（N+1 にしない）。
    targets: set[tuple[uuid.UUID, str]] = set()
    metric_keys: set[str] = set()
    every_rule_has_metric_key = True
    for row in rows:
        if row.rule_type != "metric_threshold":
            continue
        parsed = _parse_metric_context_key(row.context_key)
        if parsed is None:
            continue
        targets.add(parsed)
        metric_key = _metric_key_of(row.rule_config)
        if metric_key is None:
            every_rule_has_metric_key = False
        else:
            metric_keys.add(metric_key)
    resolved = await _resolve_metric_entities(
        session, targets, metric_keys if every_rule_has_metric_key else None
    )

    entries: list[TimelineEntry] = []
    for row in rows:
        entry = _alert_entry(row, resolved)
        if scope.vcenter_id is not None and entry.vcenter_id is not None and entry.vcenter_id != scope.vcenter_id:
            continue
        if scope.entity and not entity_matches(entry.entity_name, scope.entity):
            continue
        entries.append(entry)

    counts = count_per_bucket(
        (e.timestamp_utc for e in entries), scope.from_utc, scope.bucket_sec, scope.bucket_count
    )
    return _Collected(entries=entries, overview={"alert": counts})


def _alert_entry(row: Any, resolved: Mapping[tuple[uuid.UUID, str], _ResolvedEntity]) -> TimelineEntry:
    ref: dict[str, Any] = {
        "alert_history_id": int(row.id),
        "alert_rule_id": int(row.rule_id),
        "alert_rule_name": row.rule_name,
        "alert_state": row.state,
    }
    vcenter_id: uuid.UUID | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    detail: str | None = None
    if row.rule_type == "metric_threshold":
        metric_key = _metric_key_of(row.rule_config)
        if metric_key is not None:
            ref["metric_key"] = metric_key
        parsed = _parse_metric_context_key(row.context_key)
        if parsed is not None:
            vcenter_id, moid = parsed
            hit = resolved.get(parsed)
            if hit is not None:
                entity_name, entity_type = hit.name, hit.entity_type
        else:
            moid = row.context_key
        ref["entity_moid"] = moid
        detail = f"対象: {entity_name or moid}"
    elif row.rule_type == "event_score":
        ref["event_type"] = row.context_key
        detail = f"イベント種別: {row.context_key}"

    return TimelineEntry(
        kind="alert",
        source_id=int(row.id),
        timestamp_utc=to_utc(row.notified_at),
        level=alert_level(row.alert_level),
        title=alert_title(row.rule_name, row.state),
        detail=detail,
        entity_name=entity_name,
        entity_type=entity_type,
        vcenter_id=vcenter_id,
        ref=ref,
    )


def _parse_metric_context_key(context_key: str) -> tuple[uuid.UUID, str] | None:
    """``{vcenter_id}:{entity_moid}`` を分解する。旧形式（moid だけ）は None。"""
    if not is_vcenter_scoped_context_key(context_key):
        return None
    prefix, moid = context_key.split(":", 1)
    return uuid.UUID(prefix), moid


def _metric_key_of(config: Any) -> str | None:
    if isinstance(config, Mapping):
        value = config.get("metric_key")
        if isinstance(value, str) and value:
            return value
    return None


async def _resolve_metric_entities(
    session: AsyncSession,
    targets: set[tuple[uuid.UUID, str]],
    metric_keys: set[str] | None,
) -> dict[tuple[uuid.UUID, str], _ResolvedEntity]:
    """``(vcenter_id, entity_moid)`` ごとに、最新の ``MetricSample`` の名前と種類を返す。

    ``metric_keys`` を渡すと、その指標のサンプルだけを見る（複合インデックス
    ``(vcenter_id, entity_moid, metric_key, sampled_at)`` を最後の列まで使える）。
    ``vcenter_id`` と ``entity_moid`` はそれぞれ IN で広めに引き、組は Python 側で照合する。
    名前が空文字のときは解決できなかったものとして扱う。
    """
    if not targets:
        return {}
    vcenter_ids = sorted({vid for vid, _ in targets}, key=str)
    out: dict[tuple[uuid.UUID, str], _ResolvedEntity] = {}
    for moids in _chunks(sorted({moid for _, moid in targets}), _IN_CHUNK_SIZE):
        clauses: list[ColumnElement[bool]] = [
            MetricSample.vcenter_id.in_(vcenter_ids),
            MetricSample.entity_moid.in_(moids),
        ]
        if metric_keys:
            clauses.append(MetricSample.metric_key.in_(sorted(metric_keys)))
        ranked = (
            select(
                MetricSample.vcenter_id,
                MetricSample.entity_moid,
                MetricSample.entity_name,
                MetricSample.entity_type,
                func.row_number()
                .over(
                    partition_by=(MetricSample.vcenter_id, MetricSample.entity_moid),
                    order_by=(MetricSample.sampled_at.desc(), MetricSample.id.desc()),
                )
                .label("rn"),
            )
            .where(*clauses)
            .subquery("ranked")
        )
        stmt = select(
            ranked.c.vcenter_id, ranked.c.entity_moid, ranked.c.entity_name, ranked.c.entity_type
        ).where(ranked.c.rn == 1)
        for vid, moid, name, etype in (await session.execute(stmt)).all():
            key = (vid, moid)
            if key in targets and name:
                out[key] = _ResolvedEntity(name=name, entity_type=etype or None)
    return out


# --- 共通 -------------------------------------------------------------------------------


async def _attach_vcenter_names(
    session: AsyncSession, entries: list[TimelineEntry]
) -> list[TimelineEntry]:
    """``VCenter.name`` をまとめて引いて入れる。ハイライトにも使うので打ち切りの前に入れる。"""
    ids = {e.vcenter_id for e in entries if e.vcenter_id is not None}
    if not ids:
        return entries
    names: dict[uuid.UUID, str] = {}
    for chunk in _chunks(sorted(ids, key=str), _IN_CHUNK_SIZE):
        rows = (await session.execute(select(VCenter.id, VCenter.name).where(VCenter.id.in_(chunk)))).all()
        names.update({vid: name for vid, name in rows})
    return [
        replace(e, vcenter_name=names.get(e.vcenter_id)) if e.vcenter_id is not None else e
        for e in entries
    ]


_Collector = Callable[[AsyncSession, _Scope], Awaitable[_Collected]]

# 種別ごとの収集関数。PR4 で "metric"（metric_breach）と "log"（log_error）を足す。
_COLLECTORS: dict[TimelineSource, _Collector] = {
    "event": _collect_events,
    "alert": _collect_alerts,
}

_T = TypeVar("_T")


def _chunks(values: Sequence[_T], size: int) -> Iterator[list[_T]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)
