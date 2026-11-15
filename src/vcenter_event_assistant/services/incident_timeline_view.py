"""タイムライン画面専用 API（``POST /api/incident-timeline/view``）のサービス。

構成:

- 入口 ``build_incident_timeline_view``: 期間を秒に揃え、同時実行数の枠を取り、例外を HTTP に変換する。
- 種別ごとの収集関数（``_collect_events`` / ``_collect_alerts`` / ``_collect_metrics`` / ``_collect_logs``）:
  DB から読み、``TimelineEntry`` の列と俯瞰グラフの件数を返す。種別を足すときは収集関数を書いて
  ``_COLLECTORS`` に登録する。``sources`` に無い種別の収集関数は呼ばない（問い合わせを発行しない）。
- 純粋関数（DB を使わない）: バケット幅の選択、level の算出、並べ替え、連続のまとめ、打ち切り、ハイライト。

チャットの LLM 用集計（``services/chat/``）とは独立しており、その挙動には影響しない。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import DateTime, Integer, String, and_, case, func, literal, or_, select
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
from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    EventRecord,
    LogRecord,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.services.alerting.alert_entity_resolution import (
    IN_CHUNK_SIZE,
    MetricProbe,
    ResolvedEntity,
    chunks,
    collect_metric_probes,
    metric_key_of,
    metric_name_lookback,
    metric_probe,
    resolve_metric_entities_at,
)
from vcenter_event_assistant.services.chat.aggregation_limiter import (
    AggregationBusy,
    AggregationLimitExceeded,
    aggregation_slot,
)
from vcenter_event_assistant.services.chat.chat_period_metrics import METRIC_CPU, METRIC_MEM
from vcenter_event_assistant.services.sql_like import contains_case_insensitive
from vcenter_event_assistant.services.sql_time import (
    bucket_index_expr,
    epoch_seconds_expr,
    truncate_to_second,
)
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

# 連続するイベントをまとめる間隔の下限（秒）。merge_max_gap を参照。
_MIN_MERGE_GAP_SECONDS = 300
_TOP_ENTITIES_LIMIT = 5
_NEW_EVENT_TYPES_LIMIT = 10
# アラート側で行数の上限を超えたことを示す AggregationLimitExceeded.what
_ALERTS_LIMIT = "incident_timeline_view.alerts"
_METRICS_LIMIT = "incident_timeline_view.metrics"
_LOGS_LIMIT = "incident_timeline_view.logs"

# error 以上とみなすログの重大度（小文字にし、前後の空白を除いて比べる）と、その level。
#
# 集合はイベントの規則（_ERROR_SEVERITIES = error / critical / fatal）に、組み込みのログ収集のパーサ
# （vea_remote_log_collector.parser の LEVEL）が出す panic と、プラグインが入れ得る syslog の略称
# （err / crit / alert / emerg）を足したもの。warning 以下と、重大度の無いログは対象外。
#
# level は 1 段下げて割り当てる（error / err → warning、それより重いもの → error。critical は使わない）。
# - パーサは 1 行目に最初に現れた level の単語を重大度にするので、本文中の "error" でも付く。vCenter が
#   構造化して持つイベントの severity より確からしさが低い。
# - ログは件数が多い。打ち切りは level → 種別の順なので、通常の error ログを error にすると、warning の
#   超過区間やイベントが一覧から押し出される（7 日・200 ホストの計測で超過区間が 0 件になった）。
# - first_signal は warning 以上が対象なので、通常の error ログも兆候として選ばれる。
_LOG_LEVEL_BY_SEVERITY: dict[str, TimelineLevel] = {
    "error": "warning",
    "err": "warning",
    "critical": "error",
    "crit": "error",
    "fatal": "error",
    "panic": "error",
    "alert": "error",
    "emerg": "error",
}
_LOG_ERROR_SEVERITIES: tuple[str, ...] = tuple(sorted(_LOG_LEVEL_BY_SEVERITY))
# ログの行の entity_type。``LogRecord.host`` は収集の接続先（ESXi・vCenter のホスト名や IP）で、
# vSphere の管理対象（HostSystem など）と一致するとは限らないので、列の名前をそのまま使う。
_LOG_ENTITY_TYPE = "host"
# detail に入れるメッセージの文字数の上限（超えたら切って "…" を付ける）。
_LOG_DETAIL_MAX_CHARS = 1000

# 超過区間を判定する指標と、その日本語名。
#
# 対象は単位が % の CPU・メモリだけ。chat_period_metrics の DISK_KEYS / NET_KEYS は % ではない:
# - ``*_kbps`` は KB/s のスループット。
# - ``host.disk.usage_pct`` は名前に反して vSphere のカウンタ ``disk.usage.average``（Aggregated disk I/O
#   rate、単位 KBps）の値をそのまま保存している（collectors/host_perf_counters.py は単位を変換しない）。
# % の閾値（既定 75）を KB/s に当てると、I/O のあるホストはほぼ常に「超過」になり意味がないので、
# ``metric_threshold_disk_pct`` / ``metric_threshold_network_pct`` は受け取るが使わない。
_METRIC_LABELS: dict[str, str] = {METRIC_CPU: "CPU 使用率", METRIC_MEM: "メモリ使用率"}
# level の規則: ピークがこの値以上、または閾値をこのポイント数以上上回ったら error、それ以外は warning。
_METRIC_ERROR_PEAK_PCT = 95.0
_METRIC_ERROR_MARGIN_PCT = 15.0
_METRIC_CONTINUED_NOTE = "期間の開始前から継続"

OVERVIEW_FIELDS: tuple[str, ...] = ("event_total", "event_notable", "alert", "metric_breach", "log_error")

_LEVEL_RANK: dict[str, int] = {"info": 0, "warning": 1, "error": 2, "critical": 3}
_LEVEL_BY_RANK: dict[int, TimelineLevel] = {0: "info", 1: "warning", 2: "error", 3: "critical"}
# 同じ時刻の項目の並びと、anchor なしの打ち切りで同じ level のときの優先（小さいほど先）。
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
    - ``is_signal``: ``first_signal`` の候補にするか（回復・stale のアラートは兆候ではない）。
      俯瞰グラフの ``alert`` もこれが真のものだけを数える。
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
    is_signal: bool = True
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
    metric_name_lookback: timedelta
    # (metric_key, 閾値 %) の組。超過区間の判定に使う。
    metric_thresholds: tuple[tuple[str, float], ...] = ()
    # 隣のサンプルとの間隔がこの秒数以内なら同じ超過区間につなぐ（サンプルの欠けで区切らない）。
    metric_max_gap_seconds: int = 900


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


def merge_max_gap(bucket_sec: int) -> timedelta:
    """連続をまとめる間隔の上限。俯瞰の棒 1 本の幅か 5 分の長いほう。"""
    return timedelta(seconds=max(bucket_sec, _MIN_MERGE_GAP_SECONDS))


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


def alert_level(value: str | None, state: str | None) -> TimelineLevel:
    """通知履歴の level。

    ``alert_level`` は回復の通知でもルールの level が入るので、発火（firing）のときだけそのまま使う。
    stale は warning を上限にし、回復（画面の表記で「回復済み」になる firing・stale 以外の状態）は info にする。
    想定外の ``alert_level`` は warning として扱う。
    """
    v = (value or "").strip().lower()
    base: TimelineLevel = cast(TimelineLevel, v) if v in _ALERT_LEVELS else "warning"
    if state == "firing":
        return base
    if state == "stale":
        return base if _LEVEL_RANK[base] <= _LEVEL_RANK["warning"] else "warning"
    return "info"


def alert_title(rule_name: str, state: str | None) -> str:
    """ルール名と状態が分かる短い文。状態の語は通知履歴の画面（AlertHistoryPanel）の表記に合わせる。

    画面は firing を「発火中」、stale を「データ古い」、それ以外をすべて「回復済み」と表示する。
    """
    if state == "firing":
        return f"{rule_name} が発火"
    if state == "stale":
        return f"{rule_name} のデータが古い"
    return f"{rule_name} が回復"


def metric_breach_level(peak: float, threshold: float) -> TimelineLevel:
    """超過区間の level。ピークが 95% 以上か、閾値を 15 ポイント以上上回ったら error、それ以外は warning。

    critical は使わない（アラートや高スコアのイベントのように人が重大度を決めた信号ではないため）。
    """
    if peak >= _METRIC_ERROR_PEAK_PCT or peak - threshold >= _METRIC_ERROR_MARGIN_PCT:
        return "error"
    return "warning"


def _format_pct(value: float) -> str:
    """80.0 → "80"、82.5 → "82.5"、92.346 → "92.35"。"""
    return f"{round(float(value), 2):g}"


def metric_breach_title(metric_key: str, threshold: float) -> str:
    label = _METRIC_LABELS.get(metric_key, metric_key)
    return f"{label} が閾値（{_format_pct(threshold)}%）を超過"


def metric_breach_detail(peak: float, sample_count: int, *, continued: bool) -> str:
    """ピーク値と区間内のサンプル数。期間の開始前から続く区間はその旨を足す。

    ピークの時刻は書かない。画面が ``ref.peak_at_utc`` を利用者のタイムゾーンの設定で表示する。
    """
    parts = [f"ピーク {_format_pct(peak)}%", f"サンプル {sample_count} 件"]
    if continued:
        parts.append(_METRIC_CONTINUED_NOTE)
    return "、".join(parts)


def count_spans_per_bucket(
    spans: Iterable[tuple[datetime, datetime | None]],
    from_utc: datetime,
    bucket_sec: int,
    bucket_count: int,
) -> list[int]:
    """区間 ``[start, end or start]`` がかかるすべてのバケットで 1 ずつ数える（範囲外は切り詰める）。"""
    counts = [0] * bucket_count
    for start, end in spans:
        first = max(0, bucket_index(start, from_utc, bucket_sec))
        last = min(bucket_count - 1, bucket_index(end or start, from_utc, bucket_sec))
        for idx in range(first, last + 1):
            counts[idx] += 1
    return counts


def log_level(severity: str | None) -> TimelineLevel | None:
    """ログの重大度から level を決める。error 以上でなければ None（一覧に出さない）。"""
    return _LOG_LEVEL_BY_SEVERITY.get((severity or "").strip().lower())


def entity_matches(entity_name: str | None, needle: str) -> bool:
    """SQL 側の ``contains_case_insensitive`` と同じく、大文字小文字を区別しない部分一致。"""
    if not entity_name:
        return False
    return needle.lower() in entity_name.lower()


# --- 純粋関数: 並べ替え・まとめ・打ち切り -----------------------------------------------


def entry_sort_key(entry: TimelineEntry) -> tuple[datetime, int, int]:
    """時刻の昇順、同時刻は alert → event → metric → log の順、その中は元レコードの id の昇順。"""
    return (entry.timestamp_utc, _KIND_ORDER.get(entry.kind, len(_KIND_ORDER)), entry.source_id)


def sort_entries(entries: Iterable[TimelineEntry]) -> list[TimelineEntry]:
    return sorted(entries, key=entry_sort_key)


def merge_consecutive(
    entries: Sequence[TimelineEntry],
    *,
    max_gap: timedelta | None = None,
) -> list[TimelineEntry]:
    """時刻順に並んだ列で、``merge_key`` が等しい項目が隣り合うときだけ 1 件にまとめる。

    ``max_gap`` を渡すと、前の項目（まとめた区間の最後）からの間隔がそれを超えたときはまとめない。
    長い空白が 1 行に隠れないようにするため。

    まとめた項目は、時刻・id・参照・タイトル・詳細は最初のもの、``end_utc`` は最後の時刻、
    ``count`` は件数の合計、``score`` は最大になる。``level`` が違う項目は ``merge_key`` が違うので
    まとまらない（悪化した時点を別の行として残す）。
    """
    out: list[TimelineEntry] = []
    for entry in entries:
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.merge_key is not None
            and prev.merge_key == entry.merge_key
            and (
                max_gap is None
                or entry.timestamp_utc - (prev.end_utc or prev.timestamp_utc) <= max_gap
            )
        ):
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

    - ``anchor`` あり: ``anchor`` から区間 ``[timestamp_utc, end_utc or timestamp_utc]`` までの距離が
      小さい順（``anchor`` が区間の中なら 0）→ level が重い順 → score が高い順 → 新しい順
    - ``anchor`` なし: level が重い順 → 同じ level なら種別の順（``_KIND_ORDER``: アラート → イベント →
      メトリクス → ログ）→ score が高い順 → 新しい順。アラートは人が設定した信号なので最も先にし、
      件数が多くなりがちなログは最も後にする（大量のログで重要な行が押し出されないように）。

    それでも同じなら入力の並び（時刻・種別・元 id）で決めるので、結果は常に決定的になる。
    """
    if len(entries) <= limit:
        return list(entries), False

    def priority(indexed: tuple[int, TimelineEntry]) -> tuple[float, ...]:
        idx, e = indexed
        tail = (
            -(e.score if e.score is not None else -1),
            -e.timestamp_utc.timestamp(),
            idx,
        )
        if anchor is None:
            return (-_LEVEL_RANK[e.level], _KIND_ORDER.get(e.kind, len(_KIND_ORDER)), *tail)
        return (_distance_seconds(e, anchor), -_LEVEL_RANK[e.level], *tail)

    chosen = sorted(enumerate(entries), key=priority)[:limit]
    chosen.sort(key=lambda pair: pair[0])
    return [e for _, e in chosen], True


def _distance_seconds(entry: TimelineEntry, anchor: datetime) -> float:
    start = entry.timestamp_utc
    end = entry.end_utc or start
    if anchor < start:
        return (start - anchor).total_seconds()
    if anchor > end:
        return (anchor - end).total_seconds()
    return 0.0


# --- 純粋関数: ハイライト ---------------------------------------------------------------


def first_signal(entries: Sequence[TimelineEntry]) -> TimelineEntry | None:
    """兆候になり得る項目（``is_signal``）のうち、level が warning 以上で最も早いもの（``entries`` は時刻順）。

    回復・stale のアラートは兆候ではないので選ばない。
    """
    for e in entries:
        if e.is_signal and _LEVEL_RANK[e.level] >= _LEVEL_RANK["warning"]:
            return e
    return None


def top_entities(
    entries: Sequence[TimelineEntry],
    *,
    limit: int = _TOP_ENTITIES_LIMIT,
) -> list[IncidentTimelineTopEntity]:
    """``(vcenter_id, entity_name)`` ごとに ``count``（まとめる前の件数）を合計し、多い順に上位を返す。

    同じ名前でも vCenter が違えば別の対象として数える。同数なら最初に現れた時刻が早い順、
    それも同じなら名前・vCenter の順。``entity_type`` と ``vcenter_name`` は最初に分かった値を使う。
    """
    acc: dict[tuple[uuid.UUID | None, str], list[Any]] = {}
    for e in entries:
        if not e.entity_name:
            continue
        key = (e.vcenter_id, e.entity_name)
        slot = acc.get(key)
        if slot is None:
            acc[key] = [e.count, e.timestamp_utc, e.entity_type, e.vcenter_name]
            continue
        slot[0] += e.count
        if e.timestamp_utc < slot[1]:
            slot[1] = e.timestamp_utc
        if slot[2] is None and e.entity_type:
            slot[2] = e.entity_type
        if slot[3] is None and e.vcenter_name:
            slot[3] = e.vcenter_name
    ranked = sorted(
        acc.items(), key=lambda kv: (-kv[1][0], kv[1][1], kv[0][1], str(kv[0][0] or ""))
    )[:limit]
    return [
        IncidentTimelineTopEntity(
            entity_name=name,
            entity_type=etype,
            vcenter_id=vid,
            vcenter_name=vname,
            item_count=count,
            first_seen_utc=first_seen,
        )
        for (vid, name), (count, first_seen, etype, vname) in ranked
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
    """期間内のイベント・アラート・メトリクスの超過区間・エラーログを、個々の出来事として時刻順に返す。

    ``owner_key`` は同時実行数の上限（``aggregation_slot``）を利用者ごとに数えるための識別子。
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
                metric_name_lookback=metric_name_lookback(settings.perf_sample_interval_seconds),
                metric_max_gap_seconds=settings.effective_metric_staleness_window_seconds,
            )
    except AggregationBusy:
        raise HTTPException(
            status_code=503,
            detail="集計の処理が混み合っています。しばらく待ってから再度お試しください。",
            headers={"Retry-After": str(_BUSY_RETRY_AFTER_SECONDS)},
        ) from None
    except AggregationLimitExceeded as exc:
        raise HTTPException(status_code=422, detail=_limit_message(exc)) from None


def _limit_message(exc: AggregationLimitExceeded) -> str:
    """上限を超えた種別ごとに、実際に効く対処だけを案内する。"""
    if exc.what == _ALERTS_LIMIT:
        # 対象（entity）の絞り込みは対象を解決した後に Python 側でかけるので、行数は減らない。
        return "通知履歴が多すぎて集計できません。期間を短くしてください。"
    if exc.what == _LOGS_LIMIT:
        # vCenter と対象（ホスト名）の絞り込みは SQL で効くので、読む行数が減る。
        return (
            "エラーログが多すぎて集計できません。期間を短くする、vCenter や対象（ホスト名）で"
            "絞り込む、または種別からログを外すのいずれかをお試しください。"
        )
    if exc.what == _METRICS_LIMIT:
        # 数えるのは超過区間の数。vCenter と対象の絞り込み、閾値はどれも SQL で効くので区間の数が減る。
        return (
            "メトリクスの超過区間が多すぎて集計できません。期間を短くする、閾値を上げる、"
            "vCenter や対象で絞り込む、または種別からメトリクスを外すのいずれかをお試しください。"
        )
    return (
        "対象の出来事が多すぎて集計できません。"
        "期間を短くするか、vCenter を指定して絞り込んでください。"
    )


async def _build_in_slot(
    session: AsyncSession,
    body: IncidentTimelineViewRequest,
    ft: datetime,
    tt: datetime,
    *,
    max_rows: int,
    metric_name_lookback: timedelta,
    metric_max_gap_seconds: int,
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
        metric_name_lookback=metric_name_lookback,
        metric_thresholds=(
            (METRIC_CPU, body.metric_threshold_cpu_pct),
            (METRIC_MEM, body.metric_threshold_memory_pct),
        ),
        metric_max_gap_seconds=metric_max_gap_seconds,
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
    merged = merge_consecutive(sort_entries(entries), max_gap=merge_max_gap(bucket_sec))
    anchor = to_utc(body.anchor_time) if body.anchor_time is not None else None
    kept, truncated = select_within_limit(merged, body.item_limit, anchor)
    signal = first_signal(merged)
    # 一覧の SELECT では message を読まないので、返す項目の分だけ後から引く。
    shown = (*kept, *([signal] if signal is not None else []))
    event_details = await _event_messages(session, [e.source_id for e in shown if e.kind == "event"])
    log_details = await _log_messages(session, [e.source_id for e in shown if e.kind == "log"])
    kept = [_with_log_detail(_with_event_detail(e, event_details), log_details) for e in kept]
    if signal is not None:
        signal = _with_log_detail(_with_event_detail(signal, event_details), log_details)

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
    # message（Text）は読まない。返す項目の分だけ _event_messages で後から引く。
    list_stmt = (
        select(
            EventRecord.id,
            EventRecord.occurred_at,
            EventRecord.event_type,
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

    entries: list[TimelineEntry] = []
    for row in rows:
        level = event_level(row.notable_score, row.severity)
        entries.append(
            TimelineEntry(
                kind="event",
                source_id=int(row.id),
                timestamp_utc=to_utc(row.occurred_at),
                level=level,
                title=row.event_type,
                entity_name=row.entity_name,
                entity_type=row.entity_type,
                vcenter_id=row.vcenter_id,
                score=int(row.notable_score),
                # level が違うものはまとめない（悪化した時点を別の行として残す）
                merge_key=("event", row.event_type, row.entity_name, row.vcenter_id, level),
                ref={"event_id": int(row.id), "event_type": row.event_type},
            )
        )
    return _Collected(entries=entries, overview={"event_total": totals, "event_notable": notables})


async def _event_messages(session: AsyncSession, event_ids: Iterable[int]) -> dict[int, str]:
    """イベントの message を id でまとめて引く（IN は 500 件ごとに分割）。"""
    out: dict[int, str] = {}
    for chunk in chunks(sorted(set(event_ids)), IN_CHUNK_SIZE):
        rows = (
            await session.execute(
                select(EventRecord.id, EventRecord.message).where(EventRecord.id.in_(chunk))
            )
        ).all()
        out.update({int(eid): msg for eid, msg in rows})
    return out


def _with_event_detail(entry: TimelineEntry, messages: Mapping[int, str]) -> TimelineEntry:
    """まとめた項目は最初のイベント（``source_id``）の message を使う。空なら None。"""
    if entry.kind != "event":
        return entry
    return replace(entry, detail=messages.get(entry.source_id) or None)


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
    for chunk in chunks(sorted(event_types), IN_CHUNK_SIZE):
        stmt = (
            select(EventRecord.event_type)
            .where(*filters, EventRecord.event_type.in_(chunk))
            .group_by(EventRecord.event_type)
        )
        seen.update(str(v) for v in (await session.execute(stmt)).scalars().all())
    return seen


# --- 収集: アラート ---------------------------------------------------------------------


async def _collect_alerts(session: AsyncSession, scope: _Scope) -> _Collected:
    """``AlertHistory`` を ``occurred_at``（状態の遷移時刻。再送で変わらない）で期間に絞り、対象を解決して項目にする。

    - ``metric_threshold``: ``context_key``（``{vcenter_id}:{entity_moid}``）から vCenter と moid を取り出し、
      そのアラートのルールの指標の、``occurred_at`` の時点の ``MetricSample`` の名前・種類で対象を解決する
      （``resolve_metric_entities_at``。表示期間や居合わせるほかのアラートに依存しないので、通知履歴と同じ名前になる）。
      旧形式（moid だけ）の key は vCenter が分からず、moid は vCenter をまたいで重複し得るので、
      誤った対象に紐付けないよう名前は解決しない。
    - ``event_score``: ``context_key`` はイベント種別。対象と vCenter は持たない。
    - vCenter の絞り込みは行数の上限より前に SQL で行う。event_score は vCenter を持たないので
      全 vCenter にまたがる情報として残し、旧形式の metric の key は取り違えを避けるため除く。
    - 対象の絞り込みでは、アラートごとに「その時点の名前」が一致するものだけを残す。
    """
    stmt = (
        select(
            AlertHistory.id,
            AlertHistory.occurred_at,
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
            AlertHistory.occurred_at >= scope.from_utc,
            AlertHistory.occurred_at < scope.to_utc,
        )
        .order_by(AlertHistory.occurred_at, AlertHistory.id)
        .limit(scope.max_rows + 1)
    )
    if scope.vcenter_id is not None:
        # 行数の上限より前に vCenter で絞る。metric は context_key が "{vcenter_id}:" で始まるものだけ
        # （旧形式の moid だけの key は別の vCenter の同じ moid と取り違えるので除く）、event_score は
        # vCenter を持たないので全 vCenter にまたがる情報として残す。
        stmt = stmt.where(
            or_(
                and_(
                    AlertRule.rule_type == "metric_threshold",
                    AlertHistory.context_key.startswith(f"{scope.vcenter_id}:", autoescape=True),
                ),
                AlertRule.rule_type == "event_score",
            )
        )
    rows = (await session.execute(stmt)).all()
    if len(rows) > scope.max_rows:
        raise AggregationLimitExceeded(_ALERTS_LIMIT, scope.max_rows)

    # metric_threshold の対象を、アラートの時刻ごとにまとめて解決する（N+1 にしない）。
    probes = collect_metric_probes(
        (row.rule_type, row.context_key, row.rule_config, row.occurred_at) for row in rows
    )
    resolved = await resolve_metric_entities_at(
        session, probes, lookback=scope.metric_name_lookback
    )

    entries: list[TimelineEntry] = []
    for row in rows:
        entry = _alert_entry(row, resolved)
        if (
            scope.vcenter_id is not None
            and row.rule_type == "metric_threshold"
            and entry.vcenter_id != scope.vcenter_id
        ):
            # SQL でも絞っているが、旧形式の key（vCenter 不明）もここで確実に除く。
            continue
        if scope.entity and not entity_matches(entry.entity_name, scope.entity):
            continue
        entries.append(entry)

    # 俯瞰は発火（兆候）の件数だけを数える。回復・stale は一覧にだけ出す。
    counts = count_per_bucket(
        (e.timestamp_utc for e in entries if e.is_signal),
        scope.from_utc,
        scope.bucket_sec,
        scope.bucket_count,
    )
    return _Collected(entries=entries, overview={"alert": counts})


def _alert_entry(row: Any, resolved: Mapping[MetricProbe, ResolvedEntity]) -> TimelineEntry:
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
        metric_key = metric_key_of(row.rule_config)
        if metric_key is not None:
            ref["metric_key"] = metric_key
        probe = metric_probe(row.context_key, row.rule_config, row.occurred_at)
        if probe is not None:
            vcenter_id, moid = probe[0], probe[1]
            hit = resolved.get(probe)
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
        timestamp_utc=to_utc(row.occurred_at),
        level=alert_level(row.alert_level, row.state),
        title=alert_title(row.rule_name, row.state),
        detail=detail,
        entity_name=entity_name,
        entity_type=entity_type,
        vcenter_id=vcenter_id,
        is_signal=row.state == "firing",
        ref=ref,
    )


# --- 収集: メトリクスの超過区間 -------------------------------------------------------


async def _collect_metrics(session: AsyncSession, scope: _Scope) -> _Collected:
    """CPU・メモリの閾値超過を、生のサンプルの細かさで「開始〜終了・ピーク」の区間にまとめる。

    区間の規則（同じ ``(vcenter_id, entity_moid, metric_key)`` の中で、サンプルの時刻順に見る）:

    - 閾値以上のサンプルが続く範囲を 1 区間にする。閾値ちょうどは超過に含める。
    - 閾値未満のサンプルが 1 つでもあれば、そこで区切る。
    - 前のサンプルとの間隔が ``metric_max_gap_seconds``（アラート評価の鮮度の上限と同じ値。既定は
      収集間隔 × 3 = 15 分）を超えたら区切る。それ以内の欠け（収集の失敗）では区切らない。

    すべて DB の window 関数で行い（gaps-and-islands）、受け取るのは区間ごとに 1 行だけにする。
    サンプルを 1 行ずつ読まないので、超過が長く続いても行数は増えない（Issue #301 と同じ考え方）。
    上位 N 台に絞らない（``build_chat_period_metrics`` の上位 15 台の作りは使わない）ので、
    超過したホストはすべて出る。行数の上限（``context_aggregation_max_rows``）は区間の数に当てる。

    期間の開始前から続く超過: サンプルは ``from - metric_max_gap_seconds`` から読み、期間内の最初のサンプルの
    前のサンプル（期間の外）が閾値以上でつながっていれば「期間の開始前から継続」とする。開始・ピーク・件数は
    期間内のサンプルだけで決める（一覧と俯瞰を期間に収めるため）。
    """
    thresholds = dict(scope.metric_thresholds)
    if not thresholds:
        return _Collected(overview={"metric_breach": [0] * scope.bucket_count})
    keys = tuple(thresholds)
    scan_from = scope.from_utc - timedelta(seconds=scope.metric_max_gap_seconds)
    threshold_expr = case(
        *[(MetricSample.metric_key == key, literal(float(value))) for key, value in thresholds.items()],
    )
    clauses: list[ColumnElement[bool]] = [
        MetricSample.metric_key.in_(keys),
        MetricSample.sampled_at >= scan_from,
        MetricSample.sampled_at < scope.to_utc,
    ]
    if scope.vcenter_id is not None:
        clauses.append(MetricSample.vcenter_id == scope.vcenter_id)
    # 対象（entity）の絞り込みはここではかけない。サンプル単位で除くと、名前の違うサンプルが抜けて
    # 区間の区切りが変わるので、区間にまとめた後の名前に当てる。

    # 1. 指標ごとの閾値と超過の印（hit）
    base = (
        select(
            MetricSample.id.label("id"),
            MetricSample.vcenter_id.label("vc"),
            MetricSample.entity_moid.label("moid"),
            MetricSample.metric_key.label("mk"),
            MetricSample.sampled_at.label("at"),
            MetricSample.value.label("value"),
            func.nullif(func.trim(MetricSample.entity_name), "").label("nm"),
            MetricSample.entity_type.label("etype"),
            case((MetricSample.value >= threshold_expr, 1), else_=0).label("hit"),
        )
        .where(*clauses)
        .subquery("metric_base")
    )
    series = (base.c.vc, base.c.moid, base.c.mk)
    # 2. 同じ系列の 1 つ前のサンプル（閾値未満も含む）
    lagged = select(
        base,
        func.lag(base.c.hit).over(partition_by=series, order_by=base.c.at).label("prev_hit"),
        func.lag(base.c.at).over(partition_by=series, order_by=base.c.at).label("prev_at"),
    ).subquery("metric_lagged")
    # 3. 閾値以上のサンプルだけを残し、区間の始まり（starts=1）に印を付ける。前が閾値以上で、
    #    間隔が上限以内のときだけ前の区間の続き（starts=0）。前が無い（NULL）ときも始まり。
    gap = epoch_seconds_expr(lagged.c.at, scope.dialect_name) - epoch_seconds_expr(
        lagged.c.prev_at, scope.dialect_name
    )
    hits = (
        select(
            lagged.c.id, lagged.c.vc, lagged.c.moid, lagged.c.mk, lagged.c.at,
            lagged.c.value, lagged.c.nm, lagged.c.etype,
            case(
                (and_(lagged.c.prev_hit == 1, gap <= scope.metric_max_gap_seconds), 0),
                else_=1,
            ).label("starts"),
        )
        .where(lagged.c.hit == 1)
        .subquery("metric_hits")
    )
    hseries = (hits.c.vc, hits.c.moid, hits.c.mk)
    # 4. 始まりの印の累積和が区間の番号になる
    runs = select(
        hits,
        func.sum(hits.c.starts)
        .over(partition_by=hseries, order_by=(hits.c.at, hits.c.id), rows=(None, 0))
        .label("run"),
    ).subquery("metric_runs")
    # 5. 期間内のサンプルに絞ってから、区間ごとのピーク時刻・最初の id・最新の名前を求める
    #    （WHERE は同じ SELECT の window 関数より先に効く）
    rkey = (runs.c.vc, runs.c.moid, runs.c.mk, runs.c.run)
    in_period = (
        select(
            runs.c.vc, runs.c.moid, runs.c.mk, runs.c.run, runs.c.at, runs.c.value, runs.c.starts,
            func.first_value(runs.c.at, type_=DateTime(timezone=True))
            .over(partition_by=rkey, order_by=(runs.c.value.desc(), runs.c.at))
            .label("peak_at"),
            func.first_value(runs.c.id, type_=Integer())
            .over(partition_by=rkey, order_by=runs.c.at)
            .label("first_id"),
            # 名前は空でない最新のもの（無ければ NULL → Python で moid にする）
            func.first_value(runs.c.nm, type_=String())
            .over(partition_by=rkey, order_by=(runs.c.nm.is_(None), runs.c.at.desc()))
            .label("name"),
            func.first_value(runs.c.etype, type_=String())
            .over(partition_by=rkey, order_by=runs.c.at.desc())
            .label("etype"),
        )
        .where(runs.c.at >= scope.from_utc)
        .subquery("metric_in_period")
    )
    # 6. 区間ごとに 1 行。starts の最大が 0（期間内の行がすべて続き）なら、期間の開始前から継続している
    intervals = (
        select(
            in_period.c.vc, in_period.c.moid, in_period.c.mk,
            func.min(in_period.c.at).label("start_at"),
            func.max(in_period.c.at).label("end_at"),
            func.max(in_period.c.value).label("peak"),
            func.count().label("n"),
            func.max(in_period.c.starts).label("began_inside"),
            func.max(in_period.c.peak_at).label("peak_at"),
            func.max(in_period.c.first_id).label("first_id"),
            func.max(in_period.c.name).label("name"),
            func.max(in_period.c.etype).label("etype"),
        )
        .group_by(in_period.c.vc, in_period.c.moid, in_period.c.mk, in_period.c.run)
        .subquery("metric_intervals")
    )
    stmt = select(intervals)
    if scope.entity:
        stmt = stmt.where(contains_case_insensitive(intervals.c.name, scope.entity))
    stmt = stmt.order_by(
        intervals.c.start_at, intervals.c.vc, intervals.c.moid, intervals.c.mk
    ).limit(scope.max_rows + 1)
    rows = (await session.execute(stmt)).all()
    if len(rows) > scope.max_rows:
        raise AggregationLimitExceeded(_METRICS_LIMIT, scope.max_rows)

    entries: list[TimelineEntry] = []
    for row in rows:
        start = to_utc(row.start_at)
        end = to_utc(row.end_at)
        threshold = thresholds[row.mk]
        peak = float(row.peak)
        sample_count = int(row.n)
        continued = not int(row.began_inside)
        entries.append(
            TimelineEntry(
                kind="metric",
                source_id=int(row.first_id),
                timestamp_utc=start,
                end_utc=end if end != start else None,
                level=metric_breach_level(peak, threshold),
                title=metric_breach_title(row.mk, threshold),
                detail=metric_breach_detail(peak, sample_count, continued=continued),
                entity_name=row.name or row.moid,
                entity_type=row.etype,
                vcenter_id=row.vc,
                # 区間はそれ自体が「まとめた」行なので、隣とはまとめない。count は 1 のまま
                # （イベントの「×N」と意味が違うため。サンプル数は detail に書く）。
                merge_key=None,
                ref={
                    "metric_key": row.mk,
                    "entity_moid": row.moid,
                    "threshold_pct": float(threshold),
                    "peak_value": peak,
                    "peak_at_utc": to_utc(row.peak_at),
                    "sample_count": sample_count,
                    "continues_from_before": continued,
                },
            )
        )
    counts = count_spans_per_bucket(
        ((e.timestamp_utc, e.end_utc) for e in entries),
        scope.from_utc,
        scope.bucket_sec,
        scope.bucket_count,
    )
    return _Collected(entries=entries, overview={"metric_breach": counts})


# --- 収集: エラーログ -------------------------------------------------------------------


def _log_filters(scope: _Scope) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = [
        # occurred_at は無いことがあるので、取り込み時に決まる effective_at を使う。
        # 期間はイベントと同じ半開区間 [from, to)（ログの検索 API は to を含むが、俯瞰のバケットに揃える）。
        LogRecord.effective_at >= scope.from_utc,
        LogRecord.effective_at < scope.to_utc,
        func.lower(func.trim(LogRecord.severity)).in_(_LOG_ERROR_SEVERITIES),
    ]
    if scope.vcenter_id is not None:
        clauses.append(LogRecord.vcenter_id == scope.vcenter_id)
    if scope.entity:
        # ログには entity_name が無いので、対象の絞り込みは host に当てる。
        clauses.append(contains_case_insensitive(LogRecord.host, scope.entity))
    return clauses


async def _collect_logs(session: AsyncSession, scope: _Scope) -> _Collected:
    """重大度が error 以上の ``LogRecord``。``log_error`` の俯瞰（DB 側の GROUP BY、まとめる前の件数）と個別の行。

    level は ``log_level``（error / err は warning、それより重いものは error）。
    同じ ``(vCenter, host, log_kind, level)`` が隣り合うときは ``merge_consecutive`` で 1 行にまとめる
    （間隔の上限もイベントと同じ）。メッセージの内容はまとめの条件に入れない（入れるには一覧の SELECT で
    全行の message を読む必要があるため）。message は読まず、返す行の分だけ ``_log_messages`` で後から引く。

    ホスト名は正規化しない（FQDN と短い名前を同じホストとみなさない）。``host`` は接続先の表記
    （IP のこともある）で、イベントやメトリクスの対象名と突き合わせる確かな手がかりが無く、別のホストを
    混ぜるほうが調査を誤らせるため。
    """
    filters = _log_filters(scope)
    base = (
        select(
            bucket_index_expr(
                LogRecord.effective_at,
                scope.dialect_name,
                from_epoch=int(scope.from_utc.timestamp()),
                bucket_sec=scope.bucket_sec,
            ).label("bidx"),
        )
        .where(*filters)
        .subquery("log_base")
    )
    overview_stmt = select(base.c.bidx, func.count().label("n")).group_by(base.c.bidx)
    counts = [0] * scope.bucket_count
    for bidx, n in (await session.execute(overview_stmt)).all():
        idx = int(bidx)
        if 0 <= idx < scope.bucket_count:
            counts[idx] = int(n or 0)

    list_stmt = (
        select(
            LogRecord.id,
            LogRecord.effective_at,
            LogRecord.vcenter_id,
            LogRecord.host,
            LogRecord.log_kind,
            LogRecord.severity,
        )
        .where(*filters)
        .order_by(LogRecord.effective_at, LogRecord.id)
        .limit(scope.max_rows + 1)
    )
    rows = (await session.execute(list_stmt)).all()
    if len(rows) > scope.max_rows:
        raise AggregationLimitExceeded(_LOGS_LIMIT, scope.max_rows)

    entries: list[TimelineEntry] = []
    for row in rows:
        # SQL で error 以上に絞っているので None にはならない（Python 側の正規化が SQL と違う場合の保険）
        level = log_level(row.severity)
        if level is None:
            continue
        entries.append(
            TimelineEntry(
                kind="log",
                source_id=int(row.id),
                timestamp_utc=to_utc(row.effective_at),
                level=level,
                title=f"{row.host} {row.log_kind}",
                entity_name=row.host,
                entity_type=_LOG_ENTITY_TYPE,
                vcenter_id=row.vcenter_id,
                # level が違うもの（error と critical など）はまとめない（悪化した時点を別の行に残す）
                merge_key=("log", row.vcenter_id, row.host, row.log_kind, level),
                ref={"log_id": int(row.id)},
            )
        )
    return _Collected(entries=entries, overview={"log_error": counts})


async def _log_messages(session: AsyncSession, log_ids: Iterable[int]) -> dict[int, str]:
    """ログの message の先頭（上限 + 1 文字）を id でまとめて引く（IN は 500 件ごとに分割）。"""
    out: dict[int, str] = {}
    head = func.substr(LogRecord.message, 1, _LOG_DETAIL_MAX_CHARS + 1)
    for chunk in chunks(sorted(set(log_ids)), IN_CHUNK_SIZE):
        rows = (
            await session.execute(select(LogRecord.id, head).where(LogRecord.id.in_(chunk)))
        ).all()
        out.update({int(lid): msg for lid, msg in rows})
    return out


def truncate_detail(text: str | None, max_chars: int = _LOG_DETAIL_MAX_CHARS) -> str | None:
    """空なら None。``max_chars`` を超えたら切って "…" を付ける。"""
    if not text:
        return None
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def _with_log_detail(entry: TimelineEntry, messages: Mapping[int, str]) -> TimelineEntry:
    """まとめた行は最初のログ（``source_id``）の message を使う。"""
    if entry.kind != "log":
        return entry
    return replace(entry, detail=truncate_detail(messages.get(entry.source_id)))


# --- 共通 -------------------------------------------------------------------------------


async def _attach_vcenter_names(
    session: AsyncSession, entries: list[TimelineEntry]
) -> list[TimelineEntry]:
    """``VCenter.name`` をまとめて引いて入れる。ハイライトにも使うので打ち切りの前に入れる。"""
    ids = {e.vcenter_id for e in entries if e.vcenter_id is not None}
    if not ids:
        return entries
    names: dict[uuid.UUID, str] = {}
    for chunk in chunks(sorted(ids, key=str), IN_CHUNK_SIZE):
        rows = (await session.execute(select(VCenter.id, VCenter.name).where(VCenter.id.in_(chunk)))).all()
        names.update({vid: name for vid, name in rows})
    return [
        replace(e, vcenter_name=names.get(e.vcenter_id)) if e.vcenter_id is not None else e
        for e in entries
    ]


_Collector = Callable[[AsyncSession, _Scope], Awaitable[_Collected]]

# 種別ごとの収集関数（俯瞰のフィールド: event → event_total / event_notable、alert → alert、
# metric → metric_breach、log → log_error）。
_COLLECTORS: dict[TimelineSource, _Collector] = {
    "event": _collect_events,
    "alert": _collect_alerts,
    "metric": _collect_metrics,
    "log": _collect_logs,
}


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)
