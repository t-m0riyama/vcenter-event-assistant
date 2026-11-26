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
from collections import Counter, OrderedDict, defaultdict
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import DateTime, Integer, Row, String, and_, case, false, func, literal, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.schemas.incident_timeline_view import (
    IncidentTimelineConfigChange,
    IncidentTimelineDetectedPattern,
    IncidentTimelineHighlights,
    IncidentTimelineItemRef,
    IncidentTimelineNewEventType,
    IncidentTimelineOmittedSource,
    IncidentTimelineOverviewBucket,
    IncidentTimelineTopEntity,
    IncidentTimelineViewItem,
    IncidentTimelineViewRequest,
    IncidentTimelineViewResponse,
    TimelineLevel,
    TimelineSource,
)
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.db.models import (
    AlertHistory,
    AlertRule,
    EventRecord,
    InventoryConfigDiff,
    InventorySyncState,
    LogRecord,
    MetricSample,
    VCenter,
)
from vcenter_event_assistant.plugins.builtin import EventsCollector, TasksCollector
from vcenter_event_assistant.rules.config_changes import (
    CONFIG_CHANGE_DEFINITIONS,
    CONFIG_CHANGE_EVENT_TYPES,
    CONFIG_CHANGE_LABELS,
    config_change_kind,
)
from vcenter_event_assistant.services.alerting.alert_entity_resolution import (
    IN_CHUNK_SIZE,
    EventPatternEntityKey,
    MetricProbe,
    ResolvedEntity,
    chunks,
    collect_metric_probes,
    metric_key_of,
    metric_name_lookback,
    metric_probe,
    resolve_event_pattern_entities,
    resolve_metric_entities_at,
)
from vcenter_event_assistant.services.alerting.alert_eval_common import (
    event_pattern_context_key,
    metric_context_key,
    parse_event_pattern_context_key,
)
from vcenter_event_assistant.services.chat.aggregation_limiter import (
    AggregationBusy,
    AggregationLimitExceeded,
    aggregation_slot,
)
from vcenter_event_assistant.services.chat.chat_period_metrics import METRIC_CPU, METRIC_MEM
from vcenter_event_assistant.services.event_patterns.definitions import BUILTIN_PATTERNS
from vcenter_event_assistant.services.event_patterns.query import query_event_patterns
from vcenter_event_assistant.services.inventory_config_diffs import config_recorded_since, read_config_diffs
from vcenter_event_assistant.services.log_patterns.timeline import collect_new_log_patterns
from vcenter_event_assistant.services.metric_vcenter_filter import metric_vcenter_clause, pin_metric_covering_index
from vcenter_event_assistant.services.sql_like import contains_case_insensitive, equals_case_insensitive
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
_DETECTED_PATTERNS_LIMIT = 20
_DETECTED_PATTERN_EVENT_IDS_LIMIT = 20
CONFIG_CHANGE_MAX_ROWS = 2_000
CONFIG_CHANGE_ITEM_LIMIT = 50
_CONFIG_CHANGE_CARD_LIMIT = 20
_CONFIG_CHANGE_GROUP_GAP = timedelta(minutes=5)
_CONFIG_CHANGE_CHAIN_COLLECTORS = frozenset({EventsCollector.manifest.id, TasksCollector.manifest.id})
# アラート側で行数の上限を超えたことを示す AggregationLimitExceeded.what
_ALERTS_LIMIT = "incident_timeline_view.alerts"

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
# - ``host.disk.usage_kbps`` は vSphere のカウンタ ``disk.usage.average``（Aggregated disk I/O rate、
#   単位 KBps）の値をそのまま保存している（collectors/host_perf_counters.py は単位を変換しない）。
# % の閾値（既定 75）を KB/s に当てると、I/O のあるホストはほぼ常に「超過」になり意味がないので、
# ``metric_threshold_disk_pct`` / ``metric_threshold_network_pct`` は受け取るが使わない。
_METRIC_LABELS: dict[str, str] = {METRIC_CPU: "CPU 使用率", METRIC_MEM: "メモリ使用率"}
# level の規則: ピークがこの値以上、または閾値をこのポイント数以上上回ったら error、それ以外は warning。
_METRIC_ERROR_PEAK_PCT = 95.0
_METRIC_ERROR_MARGIN_PCT = 15.0
_METRIC_CONTINUED_NOTE = "期間の開始前から継続"
_METRIC_CONTINUES_AFTER_NOTE = "期間の終わりでも継続"

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
    # メトリクスの名前が無く、表示用に moid を入れたか。
    entity_name_is_fallback: bool = False
    config_change_kind: str | None = None
    added_config_change: bool = False
    user_name: str | None = None
    chain_id: int | None = None
    collector_id: str | None = None

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
            config_change_kind=self.config_change_kind,
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
    entity_moid: str | None = None
    # (metric_key, 閾値 %) の組。超過区間の判定に使う。
    metric_thresholds: tuple[tuple[str, float], ...] = ()
    # 隣のサンプルとの間隔がこの秒数以内なら同じ超過区間につなぐ（サンプルの欠けで区切らない）。
    metric_max_gap_seconds: int = 900
    # 区間を作る前に数える、期間内の閾値以上のサンプル数の上限。超えたらメトリクスを省く。None は数えない。
    metric_breach_sample_limit: int | None = None


@dataclass
class _Collected:
    entries: list[TimelineEntry] = field(default_factory=list)
    # OVERVIEW_FIELDS のいずれか -> バケットごとの件数（長さは bucket_count）
    overview: dict[str, list[int]] = field(default_factory=dict)
    # 行数が上限を超えたため、この種別の行を省いたか（メトリクスとログだけ。イベントとアラートは 422）
    omitted: bool = False


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


def format_number(value: float) -> str:
    """``title`` / ``detail`` の数値の書き方。画面の表示と揃える規則で、小数は 2 桁まで（丸める）、
    末尾の 0 と小数点は書かない（80 → "80"、82.5 → "82.5"、82.55 → "82.55"、92.346 → "92.35"）。

    丸めは JavaScript の ``Number.prototype.toFixed(2)`` と同じにする: 2 進の値そのもので丸め、ちょうど
    中間（0.125 など）なら大きいほうへ（``f"{v:.2f}"`` は偶数側に丸めるので 0.125 が "0.12" になり、ずれる）。
    桁が大きくても指数表記にしない。
    """
    rounded = Decimal(float(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{rounded:f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def metric_breach_title(metric_key: str, threshold: float) -> str:
    label = _METRIC_LABELS.get(metric_key, metric_key)
    return f"{label}が閾値（{format_number(threshold)}%）を超過"


def metric_breach_detail(
    peak: float, sample_count: int, *, continued: bool, continues_after: bool = False
) -> str:
    """ピーク値と区間内のサンプル数。期間の開始前から続く区間はその旨を足す。

    ピークの時刻は書かない。画面が ``ref.peak_at_utc`` を利用者のタイムゾーンの設定で表示する。
    """
    parts = [f"ピーク {format_number(peak)}%", f"サンプル {sample_count} 件"]
    if continued:
        parts.append(_METRIC_CONTINUED_NOTE)
    if continues_after:
        parts.append(_METRIC_CONTINUES_AFTER_NOTE)
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


def select_without_anchor(
    items: Sequence[TimelineEntry | IncidentTimelineViewItem], limit: int
) -> list[int]:
    """起点なしの優先順位とログの上限を適用し、選んだ項目の位置を入力順で返す。"""
    if len(items) <= limit:
        return list(range(len(items)))

    def priority(index: int) -> tuple[float, ...]:
        item = items[index]
        return (
            -_LEVEL_RANK[item.level],
            _KIND_ORDER.get(item.kind, len(_KIND_ORDER)),
            -(item.score if item.score is not None else -1),
            -to_utc(item.timestamp_utc).timestamp(),
            index,
        )

    others = sum(1 for item in items if item.kind != "log")
    log_cap = limit - min(others, limit // 4)
    chosen: list[int] = []
    logs = 0
    for index in sorted(range(len(items)), key=priority):
        if len(chosen) >= limit:
            break
        if items[index].kind == "log":
            if logs >= log_cap:
                continue
            logs += 1
        chosen.append(index)
    return sorted(chosen)


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

    ``anchor`` なしのときは、ほかの種別（アラート・イベント・メトリクス）の行があるかぎり、枠の 4 分の 1
    （切り捨て）は level に関係なくそれらに残す（ログが占めるのは最大で ``limit - limit // 4``）。重要度の順では
    同じ level のほかの種別はもともとログより前に並ぶので、この上限が効くのは、level の重いログが大量にあって
    軽いほかの種別を押し出すときだけ。ほかの種別が 4 分の 1 に満たなければ、残りはログで埋める。
    ``anchor`` ありのときは距離だけで選ぶ（ログの上限は設けない）。
    """
    if len(entries) <= limit:
        return list(entries), False
    if anchor is None:
        return [entries[index] for index in select_without_anchor(entries, limit)], True

    def priority(index: int) -> tuple[float, ...]:
        e = entries[index]
        return (
            _distance_seconds(e, anchor),
            -_LEVEL_RANK[e.level],
            -(e.score if e.score is not None else -1),
            -e.timestamp_utc.timestamp(),
            index,
        )

    chosen = sorted(range(len(entries)), key=priority)[:limit]
    return [entries[index] for index in sorted(chosen)], True


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


@dataclass(slots=True)
class _TopEntityCount:
    name: str
    first_seen: datetime
    entity_type: str | None
    vcenter_name: str | None
    count: int = 0
    latest_name_key: tuple[datetime, int, int] | None = None

    def add(self, entry: TimelineEntry) -> None:
        self.count += 1 if entry.kind == "log" else entry.count
        self.first_seen = min(self.first_seen, entry.timestamp_utc)
        if self.entity_type is None and entry.entity_type:
            self.entity_type = entry.entity_type
        if self.vcenter_name is None and entry.vcenter_name:
            self.vcenter_name = entry.vcenter_name

    def record_name(self, entry: TimelineEntry, name: str) -> None:
        timestamp, kind_order, source_id = entry_sort_key(entry)
        key = (entry.end_utc or timestamp, kind_order, source_id)
        if self.latest_name_key is None or self.latest_name_key < key:
            self.latest_name_key = key
            self.name = name


def top_entities(
    entries: Sequence[TimelineEntry],
    *,
    limit: int = _TOP_ENTITIES_LIMIT,
) -> list[IncidentTimelineTopEntity]:
    """vCenter と moid ごとに数え、moid の無い行は同名の対象が一意なら合算する。

    イベントなどは ``count``（まとめる前の件数）で数える。ログはまとめた行を 1 件として数える。
    moid のある行から先に集計し、表示名はその対象の最新の名前、種別は moid のある行の値を優先する。
    """
    by_moid: dict[tuple[uuid.UUID, str], _TopEntityCount] = {}
    name_owners: dict[tuple[uuid.UUID, str], set[str]] = {}
    named_only: list[TimelineEntry] = []
    for entry in entries:
        vid = entry.vcenter_id
        moid = entry.ref.get("entity_moid")
        name = entry.entity_name
        if vid is None or not moid:
            if name:
                named_only.append(entry)
            continue
        moid_key = (vid, moid)
        slot = by_moid.get(moid_key)
        if slot is None:
            slot = by_moid[moid_key] = _TopEntityCount(moid, entry.timestamp_utc, entry.entity_type, entry.vcenter_name)
        slot.add(entry)
        if name and not entry.entity_name_is_fallback:
            name_owners.setdefault((vid, name.lower()), set()).add(moid)
            slot.record_name(entry, name)

    by_name: dict[tuple[uuid.UUID | None, str], _TopEntityCount] = {}
    for entry in named_only:
        vid, name = entry.vcenter_id, entry.entity_name
        assert name is not None
        owners = name_owners.get((vid, name.lower())) if vid is not None else None
        if vid is not None and owners is not None and len(owners) == 1:
            by_moid[(vid, next(iter(owners)))].add(entry)
            continue
        name_key = (vid, name.lower())
        slot = by_name.get(name_key)
        if slot is None:
            slot = by_name[name_key] = _TopEntityCount(name, entry.timestamp_utc, entry.entity_type, entry.vcenter_name)
        slot.add(entry)
        slot.record_name(entry, name)

    ranked: list[tuple[uuid.UUID | None, str | None, _TopEntityCount]] = [
        (vid, moid, slot) for (vid, moid), slot in by_moid.items()
    ]
    ranked.extend((vid, None, slot) for (vid, _), slot in by_name.items())
    ranked.sort(key=lambda row: (-row[2].count, row[2].first_seen, row[2].name, str(row[0] or ""), row[1] or ""))
    return [
        IncidentTimelineTopEntity(
            entity_name=slot.name,
            entity_moid=moid,
            entity_type=slot.entity_type,
            vcenter_id=vid,
            vcenter_name=slot.vcenter_name,
            item_count=slot.count,
            first_seen_utc=slot.first_seen,
        )
        for vid, moid, slot in ranked[:limit]
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


@contextmanager
def timeline_aggregation_slot(owner_key: str) -> Iterator[None]:
    """集計と資料の生成で共通の枠を使い、空きが無ければ 503 を返す。"""
    settings = require_settings()
    try:
        with aggregation_slot(
            owner_key,
            global_limit=settings.context_aggregation_concurrency,
            per_owner_limit=settings.context_aggregation_concurrency_per_user,
        ):
            yield
    except AggregationBusy:
        raise HTTPException(
            status_code=503,
            detail="集計の処理が混み合っています。しばらく待ってから再度お試しください。",
            headers={"Retry-After": str(_BUSY_RETRY_AFTER_SECONDS)},
        ) from None


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
        with timeline_aggregation_slot(owner_key):
            return await _build_in_slot(
                session,
                body,
                ft,
                tt,
                max_rows=settings.context_aggregation_max_rows,
                metric_name_lookback=metric_name_lookback(settings.perf_sample_interval_seconds),
                metric_max_gap_seconds=settings.effective_metric_staleness_window_seconds,
                metric_breach_sample_limit=settings.timeline_metric_breach_sample_limit,
                config_retention_days=settings.inventory_config_retention_days,
            )
    except AggregationLimitExceeded as exc:
        raise HTTPException(
            status_code=422, detail=_limit_message(exc, entity_moid=body.entity_moid)
        ) from None


def _limit_message(exc: AggregationLimitExceeded, *, entity_moid: str | None) -> str:
    """上限を超えた種別ごとに、実際に効く対処だけを案内する。"""
    if exc.what == _ALERTS_LIMIT:
        if entity_moid is not None:
            return "通知履歴が多すぎて集計できません。期間を短くしてください。"
        return "通知履歴が多すぎて集計できません。期間を短くするか、vCenter を選んで絞り込んでください。"
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
    metric_breach_sample_limit: int | None = None,
    config_retention_days: int,
) -> IncidentTimelineViewResponse:
    bucket_sec = choose_bucket_seconds(ft, tt)
    n_buckets = overview_bucket_count(ft, tt, bucket_sec)
    bind = session.get_bind()
    scope = _Scope(
        from_utc=ft,
        to_utc=tt,
        vcenter_id=body.vcenter_id,
        entity=body.entity,
        entity_moid=body.entity_moid,
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
        metric_breach_sample_limit=metric_breach_sample_limit,
    )

    entries: list[TimelineEntry] = []
    overview_counts: dict[str, list[int]] = {}
    omitted: list[IncidentTimelineOmittedSource] = []
    requested = set(body.sources)
    anchor = to_utc(body.anchor_time) if body.anchor_time is not None else None
    config_to = tt
    if anchor is not None and anchor < tt:
        config_to = ft if anchor < ft else min(tt, anchor + timedelta(milliseconds=1))
    added: list[TimelineEntry] = []
    config_truncated_from: datetime | None = None
    for source, collector in _COLLECTORS.items():
        if source not in requested:
            continue
        collected = await collector(session, scope)
        entries.extend(collected.entries)
        overview_counts.update(collected.overview)
        if collected.omitted:
            omitted.append(IncidentTimelineOmittedSource(source=source, reason="too_many_rows"))
        if source == "event" and ft < config_to:
            added, config_truncated_from = await _collect_config_change_events(
                session, scope, config_to, {e.source_id for e in collected.entries}
            )

    new_types: list[IncidentTimelineNewEventType] = []
    stats = summarize_event_types(entries)
    if stats:
        seen = await _event_types_seen_in_previous_period(session, scope, stats.keys())
        new_types = pick_new_event_types(stats, seen)

    named = await _attach_vcenter_names(session, [*entries, *added])
    entries = [e for e in named if not e.added_config_change]
    added = [e for e in named if e.added_config_change]
    max_gap = merge_max_gap(bucket_sec)
    merged = merge_consecutive(sort_entries(entries), max_gap=max_gap)
    kept, truncated = select_within_limit(merged, body.item_limit, anchor)
    signal = first_signal(merged)
    added_merged = merge_consecutive(sort_entries(added), max_gap=max_gap)
    added_limit = min(CONFIG_CHANGE_ITEM_LIMIT, body.item_limit)
    added_merged.sort(key=lambda e: (config_to - (e.end_utc or e.timestamp_utc), e.source_id))
    added_kept = added_merged[:added_limit]
    kept = sort_entries([*kept, *added_kept])
    # 一覧の SELECT では message を読まないので、返す項目の分だけ後から引く。
    shown = (*kept, *([signal] if signal is not None else []))
    event_details = await _event_messages(session, [e.source_id for e in shown if e.kind == "event"])
    log_details = await _log_messages(session, [e.source_id for e in shown if e.kind == "log"])
    kept = [_with_log_detail(_with_event_detail(e, event_details), log_details) for e in kept]
    if signal is not None:
        signal = _with_log_detail(_with_event_detail(signal, event_details), log_details)

    highlights = IncidentTimelineHighlights(
        first_signal=signal.to_item() if signal is not None else None,
        top_entities=top_entities(merged),
        new_event_types=new_types,
    )
    if "log" in requested:
        await collect_new_log_patterns(
            session, highlights, _log_filters(scope), from_utc=ft, to_utc=tt, vcenter_id=scope.vcenter_id,
        )
    if "event" in requested:
        card_from = config_truncated_from or ft
        groups, counts = _summarize_config_changes(
            e for e in named if e.config_change_kind is not None and card_from <= e.timestamp_utc < config_to
        )
        highlights.config_changes = await _attach_config_diffs(
            session, groups, retention_start=utcnow() - timedelta(days=config_retention_days),
        )
        highlights.config_changes_total = sum(counts.values())
        highlights.config_change_counts = counts
        highlights.config_changes_truncated = config_truncated_from is not None
        patterns, total, omitted_patterns = await _collect_detected_patterns(session, scope)
        highlights.detected_patterns = patterns
        highlights.detected_patterns_total = total
        highlights.omitted_patterns = omitted_patterns

    return IncidentTimelineViewResponse(
        from_utc=ft,
        to_utc=tt,
        anchor_utc=anchor,
        bucket_seconds=bucket_sec,
        overview=build_overview(ft, bucket_sec, n_buckets, overview_counts),
        items=[e.to_item() for e in kept],
        truncated=truncated,
        total_items=len(merged),
        config_change_items_total=len(added_merged),
        config_change_items_shown=len(added_kept),
        config_change_items_truncated=len(added_merged) > added_limit,
        highlights=highlights,
        omitted_sources=omitted,
    )


# --- 構成変更のまとめ -------------------------------------------------------------------


_ChangeMatchKey = tuple[str, str]


@dataclass(slots=True)
class _ConfigChangeGroup:
    index: int
    kind: str
    first: TimelineEntry
    last: TimelineEntry
    target: TimelineEntry | None = None
    event_count: int = 0
    event_ids: list[int] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    user_names: list[str] = field(default_factory=list)
    match_keys: set[_ChangeMatchKey] = field(default_factory=set)
    entities: set[tuple[uuid.UUID | None, str]] = field(default_factory=set)

    def add(self, entry: TimelineEntry) -> None:
        self.last = entry
        self.event_count += 1
        if moid := entry.ref.get("entity_moid"):
            self.entities.add((entry.vcenter_id, moid))
        if len(self.event_ids) < 20:
            self.event_ids.append(entry.source_id)
        if len(self.event_types) < 5 and entry.title not in self.event_types:
            self.event_types.append(entry.title)
        if entry.user_name is not None and len(self.user_names) < 3 and entry.user_name not in self.user_names:
            self.user_names.append(entry.user_name)

    def to_card(self) -> IncidentTimelineConfigChange:
        target = self.target
        return IncidentTimelineConfigChange(
            kind=self.kind,
            label=CONFIG_CHANGE_LABELS[self.kind],
            first_utc=self.first.timestamp_utc,
            last_utc=self.last.timestamp_utc,
            vcenter_id=self.first.vcenter_id,
            vcenter_name=self.first.vcenter_name,
            entity_name=target.entity_name if target else None,
            entity_moid=target.ref.get("entity_moid") if target else None,
            entity_type=target.entity_type if target else None,
            user_names=self.user_names,
            event_types=self.event_types,
            event_count=self.event_count,
            event_ids=self.event_ids,
        )


@dataclass(slots=True)
class _ConfigChangeGroups:
    """種類と vCenter が同じ組を、chain と照合に使う対象・利用者で引けるようにする。"""

    chains: dict[int, _ConfigChangeGroup] = field(default_factory=dict)
    recent: defaultdict[_ChangeMatchKey, OrderedDict[int, _ConfigChangeGroup]] = field(
        default_factory=lambda: defaultdict(OrderedDict)
    )

    def match_target_or_user(self, entry: TimelineEntry) -> _ConfigChangeGroup | None:
        moid = entry.ref.get("entity_moid")
        name = entry.entity_name
        keys: list[_ChangeMatchKey] = []
        if moid:
            keys.append(("moid", moid))
        if name:
            keys.append(("name_without_moid" if moid else "name", name))
        if not moid and not name and entry.user_name is not None:
            keys.append(("user", entry.user_name))
        for key in keys:
            groups = self.recent.get(key)
            if groups:
                group = groups[next(reversed(groups))]
                if entry.timestamp_utc - group.last.timestamp_utc <= _CONFIG_CHANGE_GROUP_GAP:
                    return group
        return None

    def add(self, group: _ConfigChangeGroup, entry: TimelineEntry) -> None:
        moid = entry.ref.get("entity_moid")
        name = entry.entity_name
        if moid or name:
            if group.target is None:
                group.target = entry
                # 対象を持つようになった組は、以後は利用者で照合しない。
                for key in group.match_keys:
                    del self.recent[key][group.index]
                group.match_keys.clear()
            if moid:
                group.match_keys.add(("moid", moid))
            if name:
                group.match_keys.add(("name", name))
                if not moid:
                    group.match_keys.add(("name_without_moid", name))
        elif group.target is None and entry.user_name is not None:
            group.match_keys.add(("user", entry.user_name))

        group.add(entry)
        for key in group.match_keys:
            groups = self.recent[key]
            groups[group.index] = group
            groups.move_to_end(group.index)


def _summarize_config_changes(
    entries: Iterable[TimelineEntry],
) -> tuple[list[_ConfigChangeGroup], dict[str, int]]:
    groups: list[_ConfigChangeGroup] = []
    by_kind_and_vcenter: defaultdict[tuple[str, uuid.UUID | None], _ConfigChangeGroups] = defaultdict(
        _ConfigChangeGroups
    )
    for entry in sort_entries(entries):
        kind = entry.config_change_kind
        if kind is None:
            continue
        candidates = by_kind_and_vcenter[kind, entry.vcenter_id]
        chain = entry.chain_id if entry.collector_id in _CONFIG_CHANGE_CHAIN_COLLECTORS else None
        group = candidates.chains.get(chain) if chain is not None else None
        if group is None:
            group = candidates.match_target_or_user(entry)
        if group is None:
            group = _ConfigChangeGroup(index=len(groups), kind=kind, first=entry, last=entry)
            groups.append(group)
        if chain is not None:
            candidates.chains[chain] = group
        candidates.add(group, entry)

    counts = Counter(group.kind for group in groups)
    ordered_counts = {
        definition.kind: counts[definition.kind]
        for definition in CONFIG_CHANGE_DEFINITIONS
        if definition.kind in counts
    }
    groups.sort(key=lambda group: entry_sort_key(group.last), reverse=True)
    return groups[:_CONFIG_CHANGE_CARD_LIMIT], ordered_counts


async def _attach_config_diffs(
    session: AsyncSession,
    groups: list[_ConfigChangeGroup],
    *,
    retention_start: datetime,
) -> list[IncidentTimelineConfigChange]:
    cards = [group.to_card() for group in groups]
    centers = {card.vcenter_id for card in cards if card.vcenter_id is not None}
    first_success = {}
    if centers:
        first_success = dict(
            (await session.execute(
                select(InventorySyncState.vcenter_id, InventorySyncState.config_first_success_at)
                .where(InventorySyncState.vcenter_id.in_(centers))
            )).tuples().all()
        )

    padding = timedelta(minutes=2)
    for group, card in zip(groups, cards, strict=True):
        if card.vcenter_id is None or not group.entities:
            continue
        recorded_since = config_recorded_since(first_success.get(card.vcenter_id), retention_start)
        if recorded_since is None or card.last_utc < recorded_since:
            continue
        diff = InventoryConfigDiff
        card.diffs, card.diffs_total = await read_config_diffs(
            session,
            (diff.vcenter_id == card.vcenter_id)
            & diff.moid.in_([moid for center, moid in group.entities if center == card.vcenter_id]),
            from_time=card.first_utc - padding,
            to_time=card.last_utc + padding,
            newest_first=False,
        )
    return cards


# --- 収集: イベント ---------------------------------------------------------------------


async def _collect_detected_patterns(
    session: AsyncSession, scope: _Scope,
) -> tuple[list[IncidentTimelineDetectedPattern], int, list[str]]:
    detections, omitted = await query_event_patterns(
        session, scope.from_utc, scope.to_utc, vcenter_id=scope.vcenter_id, entity_moid=scope.entity_moid
    )
    if scope.entity_moid is None and scope.entity:
        detections = [d for d in detections if entity_matches(d.entity_name, scope.entity)]
    # 同順位の並びを保ちながら、時刻とレベルを降順にする。
    detections.sort(key=lambda d: (d.pattern.id, d.vcenter_id, d.entity_moid))
    detections.sort(key=lambda d: d.last_utc, reverse=True)
    detections.sort(key=lambda d: _LEVEL_RANK[d.pattern.level], reverse=True)
    kept = detections[:_DETECTED_PATTERNS_LIMIT]
    names = await _vcenter_names(session, {d.vcenter_id for d in kept})
    patterns = [
        IncidentTimelineDetectedPattern(
            pattern_id=d.pattern.id,
            title=d.pattern.title,
            description=d.pattern.description,
            level=d.pattern.level,
            vcenter_id=d.vcenter_id,
            vcenter_name=names.get(d.vcenter_id),
            entity_moid=d.entity_moid,
            entity_name=d.entity_name,
            entity_type=d.entity_type,
            first_utc=d.first_utc,
            last_utc=d.last_utc,
            event_count=len(d.event_ids),
            event_ids=list(d.event_ids[:_DETECTED_PATTERN_EVENT_IDS_LIMIT]),
        )
        for d in kept
    ]
    return patterns, len(detections), omitted


def _event_filters(
    scope: _Scope,
    from_utc: datetime,
    to_utc: datetime,
) -> list[ColumnElement[bool]]:
    entity, entity_moid = scope.entity, scope.entity_moid
    clauses: list[ColumnElement[bool]] = [
        EventRecord.occurred_at >= from_utc,
        EventRecord.occurred_at < to_utc,
    ]
    if scope.vcenter_id is not None:
        clauses.append(EventRecord.vcenter_id == scope.vcenter_id)
    if entity_moid is not None:
        match_moid = EventRecord.entity_moid == entity_moid
        if entity:
            match_moid = or_(
                match_moid,
                and_(
                    or_(EventRecord.entity_moid.is_(None), EventRecord.entity_moid == ""),
                    equals_case_insensitive(EventRecord.entity_name, entity),
                ),
            )
        clauses.append(match_moid)
    elif entity:
        clauses.append(contains_case_insensitive(EventRecord.entity_name, entity))
    return clauses


async def _collect_events(session: AsyncSession, scope: _Scope) -> _Collected:
    """``event_total`` / ``event_notable`` の俯瞰（DB 側の GROUP BY）と、``min_score`` 以上の個別イベント。"""
    filters = _event_filters(scope, scope.from_utc, scope.to_utc)

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
        select(*_EVENT_LIST_COLUMNS)
        .where(*filters, EventRecord.notable_score >= scope.min_score)
        .order_by(EventRecord.occurred_at, EventRecord.id)
        .limit(scope.max_rows + 1)
    )
    rows = (await session.execute(list_stmt)).all()
    if len(rows) > scope.max_rows:
        raise AggregationLimitExceeded("incident_timeline_view.events", scope.max_rows)

    return _Collected(
        entries=[_event_entry(row) for row in rows],
        overview={"event_total": totals, "event_notable": notables},
    )


_EVENT_LIST_COLUMNS = (
    EventRecord.id,
    EventRecord.occurred_at,
    EventRecord.event_type,
    EventRecord.severity,
    EventRecord.entity_name,
    EventRecord.entity_moid,
    EventRecord.entity_type,
    EventRecord.vcenter_id,
    EventRecord.notable_score,
    EventRecord.user_name,
    EventRecord.chain_id,
    EventRecord.collector_id,
)


def _event_entry(row: Row[Any], *, added_config_change: bool = False) -> TimelineEntry:
    level = event_level(row.notable_score, row.severity)
    ref = {"event_id": int(row.id), "event_type": row.event_type}
    if row.entity_moid:
        ref["entity_moid"] = row.entity_moid
    merge_moid = (row.entity_moid or None) if row.vcenter_id is not None else None
    return TimelineEntry(
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
        merge_key=("event", row.event_type, row.entity_name, row.vcenter_id, merge_moid, level),
        ref=ref,
        config_change_kind=config_change_kind(row.event_type),
        added_config_change=added_config_change,
        user_name=row.user_name or None,
        chain_id=row.chain_id,
        collector_id=row.collector_id,
    )


async def _collect_config_change_events(
    session: AsyncSession, scope: _Scope, window_end: datetime, ordinary_ids: set[int]
) -> tuple[list[TimelineEntry], datetime | None]:
    stmt = (
        select(*_EVENT_LIST_COLUMNS)
        .where(
            *_event_filters(scope, scope.from_utc, window_end),
            EventRecord.event_type.in_(sorted(CONFIG_CHANGE_EVENT_TYPES)),
            EventRecord.notable_score < scope.min_score,
        )
        .order_by(EventRecord.occurred_at.desc(), EventRecord.id.desc())
        .limit(CONFIG_CHANGE_MAX_ROWS + 1)
    )
    rows = (await session.execute(stmt)).all()
    # SELECT の間にスコアが再計算され、両方で読んだ id は通常の一覧にだけ残す。
    entries = [
        _event_entry(row, added_config_change=True)
        for row in rows[:CONFIG_CHANGE_MAX_ROWS]
        if row.id not in ordinary_ids
    ]
    if len(rows) <= CONFIG_CHANGE_MAX_ROWS:
        return entries, None
    # 打ち切り時は、カードの材料を足した行と同じ期間に揃える。
    oldest = entries[-1].timestamp_utc if entries else to_utc(rows[CONFIG_CHANGE_MAX_ROWS - 1].occurred_at)
    return entries, oldest


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
    filters = _event_filters(scope, prev_from, scope.from_utc)
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
    - ``event_pattern``: ``context_key`` の vCenter と moid で、保持されている最新のイベントの対象名を引く。
    - ``event_score``: ``context_key`` はイベント種別。対象と vCenter は持たない。
    - vCenter の絞り込みは行数の上限より前に SQL で行う。event_score は vCenter を持たないので
      全 vCenter にまたがる情報として残し、旧形式の metric の key は取り違えを避けるため除く。
    - moid の指定は metric_threshold と event_pattern の key の完全一致で SQL で絞る。名前だけの指定は解決後の名前に当てる。
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
    if scope.entity_moid is not None and scope.vcenter_id is not None:
        stmt = stmt.where(
            or_(
                and_(
                    AlertRule.rule_type == "metric_threshold",
                    AlertHistory.context_key == metric_context_key(scope.vcenter_id, scope.entity_moid),
                ),
                and_(
                    AlertRule.rule_type == "event_pattern",
                    AlertHistory.context_key.in_([
                        event_pattern_context_key(scope.vcenter_id, scope.entity_moid, pattern.id)
                        for pattern in BUILTIN_PATTERNS
                    ]),
                ),
            )
        )
    elif scope.vcenter_id is not None:
        # 対象を持つアラートは、行数の上限より前に vCenter で絞る。
        # event_score は vCenter にまたがる情報として残す。
        stmt = stmt.where(
            or_(
                and_(
                    AlertRule.rule_type.in_(("metric_threshold", "event_pattern")),
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

    pattern_entities = await resolve_event_pattern_entities(
        session, (row.context_key for row in rows if row.rule_type == "event_pattern"),
    )
    entries: list[TimelineEntry] = []
    for row in rows:
        entry = _alert_entry(row, resolved, pattern_entities)
        if (
            scope.vcenter_id is not None
            and row.rule_type in ("metric_threshold", "event_pattern")
            and entry.vcenter_id != scope.vcenter_id
        ):
            # SQL でも絞っているが、旧形式の key（vCenter 不明）もここで確実に除く。
            continue
        if scope.entity_moid is None and scope.entity and not entity_matches(entry.entity_name, scope.entity):
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


def _alert_entry(
    row: Any,
    resolved: Mapping[MetricProbe, ResolvedEntity],
    pattern_entities: Mapping[EventPatternEntityKey, ResolvedEntity],
) -> TimelineEntry:
    ref: dict[str, Any] = {
        "alert_history_id": int(row.id),
        "alert_rule_id": int(row.rule_id),
        "alert_rule_name": row.rule_name,
        "alert_rule_type": row.rule_type,
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
    elif row.rule_type == "event_pattern":
        parsed = parse_event_pattern_context_key(row.context_key)
        if parsed is not None:
            vcenter_id, moid, pattern_id = parsed
            ref["entity_moid"] = moid
            hit = pattern_entities.get((vcenter_id, moid))
            if hit is not None:
                entity_name, entity_type = hit.name, hit.entity_type
            pattern = next((pattern for pattern in BUILTIN_PATTERNS if pattern.id == pattern_id), None)
            target = f"{entity_name} ({moid})" if entity_name else moid
            detail = f"{pattern.title if pattern else pattern_id} / 対象: {target}"
            if pattern is not None:
                detail = f"{detail} / {pattern.description}"
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

    読む量を抑えるため、期間内の**閾値以上のサンプルだけ**を読む。区切りの判定は、1 つ前の閾値以上の
    サンプルとの間隔と、その間に別のサンプル（必ず閾値未満）があるかで決め、後者は既存の索引
    ``(vcenter_id, entity_moid, metric_key, sampled_at)`` だけで確かめる（表を引かない）。表を引いて直前の
    サンプルの値を見るのは、系列ごとに期間内の最初の行（期間の開始前からの継続の判定）だけ。
    区間への番号付けとピーク・名前の算出は、閾値以上のサンプルだけに window 関数をかけて DB で行い、
    受け取るのは区間ごとに 1 行だけにする（超過が長く続いても行数は増えない。Issue #301 と同じ考え方）。
    以前は期間内の全サンプルに window 関数をかけており、7 日・200 ホストで SQLite は 12〜16 秒かかった。
    費用は閾値以上のサンプルの数に比例するので、超過が多いと時間が延びる（目安は運用ドキュメント）。

    上位 N 台に絞らない（``build_chat_period_metrics`` の上位 15 台の作りは使わない）ので、超過したホストは
    すべて出る。行数の上限（``context_aggregation_max_rows``）は区間の数に当て、超えたら 422 にせず
    超過区間の行を省く（``omitted``）。

    時間の上限: 区間の問い合わせの前に、それが読む閾値以上のサンプル（期間内、CPU とメモリの合計、vCenter・
    対象で絞った後）を ``metric_breach_sample_limit`` + 1 件で打ち切って数え、上限を超えたら区間の問い合わせを
    実行せずに省く（``omitted``。理由は区間の数のときと同じ ``too_many_rows``）。打ち切るので、数え上げ自体も
    上限に比例する時間で終わる。

    期間の端:

    - 開始前から続く超過: 期間内の最初のサンプルの直前のサンプル（期間の外）が閾値以上でつながっていれば
      ``continues_from_before``。開始・ピーク・件数は期間内のサンプルだけで決める。
    - 終わりでも続く超過（``continues_after``）: 区間の最後のサンプルが、その系列の期間内の最後のサンプルで
      （その後に閾値未満のサンプルも、つながらないサンプルも無い）、かつ期間の終わりから間隔の上限以内に
      あるとき。期間の終わりは ``to`` だが、``to`` が未来なら現在時刻にする（まだ来ていないサンプルを
      途絶えとみなさない）。上限より前で途絶えた系列は、その後も超過していたとは言えないので偽にする。
      上限ちょうどは真（その時点で次のサンプルが来れば、区間をつなぐ規則でも同じ区間になるため）。
      期間の後ろのサンプルは読まない（「最後に見えたサンプルの時点で、まだ超過していた」という意味）。
    """
    thresholds = dict(scope.metric_thresholds)
    if not thresholds:
        return _Collected(overview={"metric_breach": [0] * scope.bucket_count})
    keys = tuple(thresholds)
    max_gap = scope.metric_max_gap_seconds

    def threshold_of(metric_key_column: Any) -> Any:
        return case(
            *[(metric_key_column == key, literal(float(value))) for key, value in thresholds.items()],
        )

    vcenter_clause = await metric_vcenter_clause(session, scope.vcenter_id)
    if vcenter_clause is None:
        return _Collected(overview={"metric_breach": [0] * scope.bucket_count})
    clauses: list[ColumnElement[bool]] = [
        MetricSample.metric_key.in_(keys),
        MetricSample.sampled_at >= scope.from_utc,
        MetricSample.sampled_at < scope.to_utc,
        MetricSample.value >= threshold_of(MetricSample.metric_key),
        vcenter_clause,
    ]
    # 名前（entity）での絞り込みは、サンプル単位ではかけない。名前の違うサンプルが抜けて区間の区切りが変わる
    # ため。代わりに、名前（空なら moid）が対象に当たる閾値以上のサンプルを 1 件でも持つ系列に絞り、系列の中の
    # サンプルはすべて残す。区間の名前（区間の中の空でない最新の名前、無ければ moid）は、その区間のどれかの
    # サンプルの名前か moid なので、対象に当たる区間はかならずこの系列に入る（区間の名前での絞り込みは最後に
    # かける）。数え上げも区間の問い合わせも、絞った後のサンプルだけを読む。
    #
    # SQLite では、metric_samples を読む select（matching_series・capped・hits0）を vCenter・指標・期間の被覆索引に
    # 固定する（Issue #334）。名前や moid の指定の有無にかかわらず、指標と期間の範囲走査にこの索引を使う。
    # 固定しないと、新しい SQLite（3.51.0 以降で確認）は期間内の全指標を読む。matching_series は、古い SQLite でも
    # vCenter を指定しないと、系列の索引 (vcenter_id=?) でその vCenter の全履歴を読む。別名（metric_prev・metric_between
    # など）は 1 行ずつ引く問い合わせなので固定しない。
    if scope.entity_moid is not None:
        # moid は系列のキーなので、サンプル単位で絞っても区間の区切りは変わらない。
        clauses.append(MetricSample.entity_moid == scope.entity_moid)
    elif scope.entity:
        matching_series = pin_metric_covering_index(
            select(MetricSample.vcenter_id, MetricSample.entity_moid, MetricSample.metric_key)
            .where(
                *clauses,
                contains_case_insensitive(
                    func.coalesce(func.nullif(func.trim(MetricSample.entity_name), ""), MetricSample.entity_moid),
                    scope.entity,
                ),
            )
            .distinct()
        )
        # entity_moid || '' は値を変えない。列のままだと SQLite が系列の索引 (vcenter_id, entity_moid, ...) で
        # 系列ごとに期間内の全サンプルを表から読む計画を選ぶので、値まで含む索引で閾値以上の行だけを読ませる。
        clauses.append(
            tuple_(MetricSample.vcenter_id, MetricSample.entity_moid.concat(""), MetricSample.metric_key).in_(
                matching_series
            )
        )

    limit = scope.metric_breach_sample_limit
    if limit is not None:
        # 上限 + 1 件で打ち切って数える（全件は数えない）
        capped = pin_metric_covering_index(select(literal(1)).select_from(MetricSample).where(*clauses).limit(limit + 1))
        breaching = (
            await session.execute(select(func.count()).select_from(capped.subquery("metric_breach_count")))
        ).scalar_one()
        if breaching > limit:
            return _Collected(overview={"metric_breach": [0] * scope.bucket_count}, omitted=True)

    # 列の順は意味を変えない。索引 (vcenter_id, entity_moid, metric_key, sampled_at) の並びと一致させると、
    # SQLite が並べ替えを省くためにその索引で期間外も含む全サンプルを読む計画を選ぶので、わざと順を変える。
    def series_of(sub: Any) -> tuple[Any, Any, Any]:
        return (sub.c.mk, sub.c.moid, sub.c.vc)

    # 1. 期間内の閾値以上のサンプル
    hits0 = pin_metric_covering_index(
        select(
            MetricSample.id.label("id"),
            MetricSample.vcenter_id.label("vc"),
            MetricSample.entity_moid.label("moid"),
            MetricSample.metric_key.label("mk"),
            MetricSample.sampled_at.label("at"),
            MetricSample.value.label("value"),
            func.nullif(func.trim(MetricSample.entity_name), "").label("nm"),
            MetricSample.entity_type.label("etype"),
        ).where(*clauses)
    ).subquery("metric_hits0")
    # 2. 同じ系列の 1 つ前の閾値以上のサンプルの時刻（期間内）
    lagged = select(
        hits0,
        func.lag(hits0.c.at).over(partition_by=series_of(hits0), order_by=hits0.c.at).label("prev_hit_at"),
    ).subquery("metric_hits_lagged")
    # 3. 区間の始まり（starts=1）の印。読む量を抑えるため、表を引くのは系列ごとに期間内の最初の行だけにする。
    #    - 期間内の最初の行（1 つ前の閾値以上の行が無い）: 直前のサンプル（期間の前でもよい）が閾値以上で、
    #      間隔が上限以内なら続き（期間の開始前から継続）。直前のサンプルは索引の seek 1 回で引く。
    #    - それ以外: 1 つ前の閾値以上の行との間隔が上限を超えたら始まり。上限以内でも、その間に別のサンプルが
    #      あれば始まり（間に挟まるサンプルは必ず閾値未満。閾値以上なら 1 つ前の行になっているため）。
    #      間のサンプルの有無は、索引 (vcenter_id, entity_moid, metric_key, sampled_at) だけで分かる（表を引かない）。
    prev = aliased(MetricSample, name="metric_prev")
    prev_hit_epoch = (
        select(
            case(
                (
                    prev.value >= threshold_of(prev.metric_key),
                    epoch_seconds_expr(prev.sampled_at, scope.dialect_name),
                ),
                else_=None,
            )
        )
        .where(
            prev.vcenter_id == lagged.c.vc,
            prev.entity_moid == lagged.c.moid,
            prev.metric_key == lagged.c.mk,
            prev.sampled_at < lagged.c.at,
        )
        .order_by(prev.sampled_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    between = aliased(MetricSample, name="metric_between")
    sample_between = (
        select(between.id)
        .where(
            between.vcenter_id == lagged.c.vc,
            between.entity_moid == lagged.c.moid,
            between.metric_key == lagged.c.mk,
            between.sampled_at > lagged.c.prev_hit_at,
            between.sampled_at < lagged.c.at,
        )
        .exists()
    )
    at_epoch = epoch_seconds_expr(lagged.c.at, scope.dialect_name)
    hits = (
        select(
            lagged.c.id, lagged.c.vc, lagged.c.moid, lagged.c.mk, lagged.c.at,
            lagged.c.value, lagged.c.nm, lagged.c.etype,
            case(
                (
                    lagged.c.prev_hit_at.is_(None),
                    case((at_epoch - prev_hit_epoch <= max_gap, 0), else_=1),
                ),
                (at_epoch - epoch_seconds_expr(lagged.c.prev_hit_at, scope.dialect_name) > max_gap, 1),
                (sample_between, 1),
                else_=0,
            ).label("starts"),
        )
        # OFFSET 0 は最適化の壁。PostgreSQL がこの副問い合わせを外側に展開すると、starts を使う箇所ごとに
        # 相関副問い合わせを実行し直す（2 回になる）ので、ここで 1 回だけ求めさせる。
        .offset(0)
        .subquery("metric_hits")
    )
    hseries = series_of(hits)
    # 3. 始まりの印の累積和が区間の番号になる
    runs = select(
        hits,
        func.sum(hits.c.starts)
        .over(partition_by=hseries, order_by=(hits.c.at, hits.c.id), rows=(None, 0))
        .label("run"),
    ).subquery("metric_runs")
    # 4. 区間ごとのピーク時刻・最初の id・最新の名前
    rkey = (runs.c.mk, runs.c.moid, runs.c.vc, runs.c.run)
    run_stats = select(
        runs.c.vc, runs.c.moid, runs.c.mk, runs.c.run, runs.c.at, runs.c.value, runs.c.starts,
        func.first_value(runs.c.at, type_=DateTime(timezone=True))
        .over(partition_by=rkey, order_by=(runs.c.value.desc(), runs.c.at))
        .label("peak_at"),
        func.first_value(runs.c.id, type_=Integer())
        .over(partition_by=rkey, order_by=runs.c.at)
        .label("first_id"),
        # 名前は空でない最新のもの（無ければ NULL → 表示も絞り込みも moid）
        func.first_value(runs.c.nm, type_=String())
        .over(partition_by=rkey, order_by=(runs.c.nm.is_(None), runs.c.at.desc()))
        .label("name"),
        runs.c.etype,
    ).subquery("metric_run_stats")
    # 5. 区間ごとに 1 行。starts の最大が 0（期間内の行がすべて続き）なら、期間の開始前から継続している
    intervals = (
        select(
            run_stats.c.vc, run_stats.c.moid, run_stats.c.mk,
            func.min(run_stats.c.at).label("start_at"),
            func.max(run_stats.c.at).label("end_at"),
            func.max(run_stats.c.value).label("peak"),
            func.count().label("n"),
            func.max(run_stats.c.starts).label("began_inside"),
            func.max(run_stats.c.peak_at).label("peak_at"),
            func.max(run_stats.c.first_id).label("first_id"),
            func.max(run_stats.c.name).label("name"),
            func.max(run_stats.c.etype).label("etype"),
        )
        .group_by(run_stats.c.vc, run_stats.c.moid, run_stats.c.mk, run_stats.c.run)
        .subquery("metric_intervals")
    )
    # 6. 区間の最後のサンプルより後に、期間内のサンプルがあるか（あれば期間の終わりまでに区間は終わっている）
    later = aliased(MetricSample, name="metric_later")
    has_later = (
        select(later.id)
        .where(
            later.vcenter_id == intervals.c.vc,
            later.entity_moid == intervals.c.moid,
            later.metric_key == intervals.c.mk,
            later.sampled_at > intervals.c.end_at,
            later.sampled_at < scope.to_utc,
        )
        .exists()
    )
    stmt = select(intervals, has_later.label("has_later"))
    if scope.entity_moid is None and scope.entity:
        # 表示と同じ規則（名前が空なら moid）に当てる。moid で表示した行も「この対象で絞る」で消えない。
        stmt = stmt.where(
            contains_case_insensitive(func.coalesce(intervals.c.name, intervals.c.moid), scope.entity)
        )
    stmt = stmt.order_by(
        intervals.c.start_at, intervals.c.vc, intervals.c.moid, intervals.c.mk
    ).limit(scope.max_rows + 1)
    if scope.dialect_name == "postgresql":
        # PostgreSQL は閾値以上の行数を大きく見積もる（value >= CASE ... の選択率が分からない）ため、
        # 期間が長いと JIT のコンパイルが走り、実行より長くかかる（7 日・200 ホストで 1.3 秒のうち 0.8 秒）。
        # このトランザクションの残りだけ JIT を切る（タイムラインの問い合わせはどれも JIT が要らない）。
        await session.execute(text("SET LOCAL jit = off"))
    rows = (await session.execute(stmt)).all()
    if len(rows) > scope.max_rows:
        # 422 にせず、超過区間の行だけを省く（イベントやアラートまで見えなくしない）。区間を作れないので
        # 俯瞰も数えられない。画面は omitted_sources で 0 と「分からない」を区別する。
        return _Collected(overview={"metric_breach": [0] * scope.bucket_count}, omitted=True)

    # 期間の終わり。to が未来なら現在時刻（まだ来ていないサンプルを途絶えとみなさない）。
    observed_until = min(scope.to_utc, datetime.now(timezone.utc))
    entries: list[TimelineEntry] = []
    for row in rows:
        start = to_utc(row.start_at)
        end = to_utc(row.end_at)
        threshold = thresholds[row.mk]
        peak = float(row.peak)
        sample_count = int(row.n)
        continued = not int(row.began_inside)
        continues_after = not row.has_later and (observed_until - end).total_seconds() <= max_gap
        entries.append(
            TimelineEntry(
                kind="metric",
                source_id=int(row.first_id),
                timestamp_utc=start,
                end_utc=end if end != start else None,
                level=metric_breach_level(peak, threshold),
                title=metric_breach_title(row.mk, threshold),
                detail=metric_breach_detail(
                    peak, sample_count, continued=continued, continues_after=continues_after
                ),
                entity_name=row.name or row.moid,
                entity_name_is_fallback=not row.name,
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
                    "continues_after": continues_after,
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
    ]
    if scope.vcenter_id is not None:
        clauses.append(LogRecord.vcenter_id == scope.vcenter_id)
    if scope.entity:
        # ログには entity_name が無いので、対象の絞り込みは host に当てる。
        match_name = equals_case_insensitive if scope.entity_moid is not None else contains_case_insensitive
        clauses.append(match_name(LogRecord.host, scope.entity))
    elif scope.entity_moid is not None:
        clauses.append(false())
    return clauses


async def _collect_logs(session: AsyncSession, scope: _Scope) -> _Collected:
    """重大度が error 以上の ``LogRecord``。``log_error`` の俯瞰（DB 側の GROUP BY、まとめる前の件数）と個別の行。

    level は ``log_level``（error / err は warning、それより重いものは error）。
    同じ ``(vCenter, host, log_kind, level)`` が隣り合うときは ``merge_consecutive`` で 1 行にまとめる
    （間隔の上限もイベントと同じ）。メッセージの内容はまとめの条件に入れない（入れるには一覧の SELECT で
    全行の message を読む必要があるため）。message は読まず、返す行の分だけ ``_log_messages`` で後から引く。
    行数が上限（``context_aggregation_max_rows``）を超えたら、422 にせずログの行を省く（``omitted``）。
    俯瞰の ``log_error`` は GROUP BY の件数なので、省いたときも返す。

    ホスト名は正規化しない（FQDN と短い名前を同じホストとみなさない）。``host`` は接続先の表記
    （IP のこともある）で、イベントやメトリクスの対象名と突き合わせる確かな手がかりが無く、別のホストを
    混ぜるほうが調査を誤らせるため。
    """
    if scope.entity_moid is not None and scope.entity is None:
        return _Collected()
    filters = [
        *_log_filters(scope),
        func.lower(func.trim(LogRecord.severity)).in_(_LOG_ERROR_SEVERITIES),
    ]
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
        # ORDER BY は付けない（Python で並べる）。上限 + 1 行で超えたかを見るだけなので SQL 側の並びは要らず、
        # 付けると SQLite が並べ替えを省くために (vcenter_id, effective_at) などの索引を選び、期間内の全ログを読む。
        .limit(scope.max_rows + 1)
    )
    rows = sorted((await session.execute(list_stmt)).all(), key=lambda r: (to_utc(r.effective_at), r.id))
    if len(rows) > scope.max_rows:
        # 422 にせず、ログの行だけを省く（イベントやアラートまで見えなくしない）。俯瞰の件数は返す。
        return _Collected(overview={"log_error": counts}, omitted=True)

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
    names = await _vcenter_names(session, ids)
    return [
        replace(e, vcenter_name=names.get(e.vcenter_id)) if e.vcenter_id is not None else e
        for e in entries
    ]


async def _vcenter_names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    names: dict[uuid.UUID, str] = {}
    for chunk in chunks(sorted(ids, key=str), IN_CHUNK_SIZE):
        rows = (await session.execute(select(VCenter.id, VCenter.name).where(VCenter.id.in_(chunk)))).all()
        names.update({vid: name for vid, name in rows})
    return names


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
