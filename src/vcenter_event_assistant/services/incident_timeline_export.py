"""タイムラインの調査資料を Markdown または ZIP にする。"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import chain, islice
from typing import Literal
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from zoneinfo import ZoneInfo

from pydantic import JsonValue

from vcenter_event_assistant.api.datetime_utils import to_utc
from vcenter_event_assistant.api.schemas.incident_timeline_view import (
    IncidentTimelineSavedViewRequest,
    IncidentTimelineViewItem,
    IncidentTimelineViewRequest,
    IncidentTimelineViewResponse,
    TimelineSource,
)
from vcenter_event_assistant.rules.config_changes import CONFIG_CHANGE_LABELS
from vcenter_event_assistant.services.incident_timeline_view import (
    OVERVIEW_FIELDS,
    select_without_anchor,
)
from vcenter_event_assistant.services.log_export import neutralize_csv_formula
from vcenter_event_assistant.services.log_patterns.severity import severity_name

ExportFormat = Literal["md", "zip"]
ViewRequest = IncidentTimelineViewRequest | IncidentTimelineSavedViewRequest

DETAIL_MAX_CHARS = 2000
RESULT_MAX_BYTES = 8 * 1024 * 1024
_DETAIL_CUT_MARK = "…（出力時に切り詰めました）"
_CONDITIONS_UNREADABLE = "保存した条件を読めません"
_NOTABLE_LIMIT = 100
_CELL_LIMIT = 200
_HIGHLIGHT_LIMIT = 300
_SOURCES: dict[TimelineSource, str] = {
    "event": "イベント",
    "alert": "アラート",
    "metric": "メトリクス",
    "log": "ログ",
}
_OMITTED_SOURCE_REASONS = {"too_many_rows": "行数が上限を超えた"}
_LINE_BREAKS = frozenset("\r\n\u2028\u2029\t")
_BACKTICKS = re.compile(r"`+")
_ITEM_COLUMNS = (
    "timestamp",
    "timestamp_utc_offset",
    "kind_label",
    "level",
    "vcenter_name",
    "entity_name",
    "title",
    "detail",
    "count",
    "score",
    "id",
    "kind",
    "entity_type",
    "vcenter_id",
    "entity_moid",
    "end",
    "end_utc_offset",
    "event_id",
    "event_type",
    "alert_history_id",
    "alert_rule_id",
    "alert_rule_name",
    "alert_rule_type",
    "alert_state",
    "metric_key",
    "log_id",
    "threshold_pct",
    "peak_value",
    "peak_at",
    "peak_at_utc_offset",
    "sample_count",
    "continues_from_before",
    "continues_after",
    "time_zone",
    "config_change_kind",
)
_TEXT_COLUMNS = frozenset(
    (
        "title",
        "detail",
        "entity_name",
        "entity_type",
        "vcenter_name",
        "event_type",
        "alert_rule_name",
        "alert_rule_type",
        "alert_state",
        "metric_key",
        "entity_moid",
        "config_change_kind",
    )
)


class ExportResultTooLarge(Exception):
    """ZIP に入れる結果の JSON が上限を超えた。"""


@dataclass(frozen=True)
class SavedSnapshotSource:
    """保存時点の出典と、報告書に添えるメモ。"""

    id: UUID
    saved_at: datetime
    operator_note: str


def _printable(char: str) -> bool:
    return unicodedata.category(char) not in {"Cc", "Cf"}


def _fence(value: str, *, minimum: int) -> str:
    return "`" * max(
        minimum, max((len(run[0]) for run in _BACKTICKS.finditer(value)), default=0) + 1
    )


def _code(
    value: str | None, *, limit: int = _HIGHLIGHT_LIMIT, cell: bool = False
) -> str:
    normalized = (
        " " if char in _LINE_BREAKS else char
        for char in (value or "")
        if char in _LINE_BREAKS or _printable(char)
    )
    text = "".join(islice(normalized, limit + 1))
    if len(text) > limit:
        text = text[:limit] + "…"
    if not text.strip():
        return "-"
    if cell:
        text = text.replace("|", "｜")
    fence = _fence(text, minimum=1)
    return f"{fence} {text} {fence}"


def _note(value: str) -> str:
    cleaned = "".join(
        char
        for char in value.replace("\r\n", "\n").replace("\r", "\n")
        if char in "\n\t" or _printable(char)
    )
    fence = _fence(cleaned, minimum=3)
    trailing_newline = "" if not cleaned or cleaned.endswith("\n") else "\n"
    return f"{fence}\n{cleaned}{trailing_newline}{fence}"


def _csv_time(value: datetime | None, zone: ZoneInfo) -> tuple[str, str]:
    if value is None:
        return "", ""
    local = to_utc(value).astimezone(zone).isoformat(sep=" ", timespec="seconds")
    return local[:19].replace("-", "/"), local[19:]


def _time(value: datetime | None, zone: ZoneInfo) -> str:
    return " ".join(_csv_time(value, zone)) if value is not None else "-"


def _vcenter_name(
    result: IncidentTimelineViewResponse, vcenter_id: UUID, current_name: str | None
) -> str:
    candidates = chain(
        result.items,
        result.highlights.top_entities,
        result.highlights.detected_patterns,
    )
    return next(
        (
            item.vcenter_name
            for item in candidates
            if item.vcenter_id == vcenter_id and item.vcenter_name
        ),
        current_name or str(vcenter_id),
    )


def _conditions(
    result: IncidentTimelineViewResponse,
    request: ViewRequest | None,
    zone: ZoneInfo,
    current_vcenter_name: str | None,
) -> list[str]:
    if request is None:
        return [
            f"- 期間: {_time(result.from_utc, zone)} ～ {_time(result.to_utc, zone)}",
            f"- その他の条件: {_CONDITIONS_UNREADABLE}",
        ]
    vcenter = (
        _code(_vcenter_name(result, request.vcenter_id, current_vcenter_name))
        if request.vcenter_id is not None
        else "すべて"
    )
    sources = "、".join(_code(source) for source in request.sources or ()) or "-"
    entity_label = (
        "対象（部分一致）"
        if request.entity_moid is None
        else "対象（moid の無いイベント・ログの完全一致）"
    )
    return [
        f"- 期間: {_time(request.from_time, zone)} ～ {_time(request.to_time, zone)}",
        f"- 起点: {_time(request.anchor_time, zone)}",
        f"- vCenter: {vcenter}",
        f"- {entity_label}: {_code(request.entity)}",
        f"- 対象の moid: {_code(request.entity_moid)}",
        f"- 種別: {sources}",
        f"- min_score: {_number(request.min_score)}",
        f"- メトリクスのしきい値: CPU {_percent(request.metric_threshold_cpu_pct)}、"
        f"メモリ {_percent(request.metric_threshold_memory_pct)}",
    ]


def _number(value: int | float | None) -> str:
    return "-" if value is None else str(value)


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value:g}%"


def _overview(result: IncidentTimelineViewResponse) -> list[str]:
    omitted = "、".join(
        f"{_SOURCES[item.source]}（{_OMITTED_SOURCE_REASONS[item.reason]}）"
        for item in result.omitted_sources
    )
    counts = Counter(item.kind for item in result.items)
    count_label = "（表示した範囲の件数）" if result.truncated or result.config_change_items_truncated else ""
    added_count = result.config_change_items_shown
    shown = len(result.items) - added_count
    lines = [
        f"- 出来事: {shown} 件 / 総数 {result.total_items} 件",
        f"- 打ち切り: {'あり' if result.truncated else 'なし'}",
        f"- 省いた種別: {omitted or '-'}",
        f"- 種類ごとの件数{count_label}: "
        + "、".join(
            f"{label} {counts[source]} 件" for source, label in _SOURCES.items()
        ),
    ]
    if added_count:
        lines.append(f"- 追加した構成変更の行: {added_count} 件")
    if result.config_change_items_truncated:
        lines.append(
            f"- 構成変更の行は起点（または期間の終わり）に近い {added_count} 件だけを一覧に表示"
        )
    return lines


def _highlights(result: IncidentTimelineViewResponse, zone: ZoneInfo) -> list[str]:
    highlights = result.highlights
    signal = highlights.first_signal
    lines = ["### 最初の兆候", ""]
    if signal is None:
        lines.append("なし")
    else:
        lines.append(
            f"- {_time(signal.timestamp_utc, zone)} / {_SOURCES[signal.kind]} / {signal.level} / "
            f"{_code(signal.entity_name or signal.ref.entity_moid)} / {_code(signal.title)} / {_code(signal.detail)}"
        )
    lines.extend(("", "### 影響の大きい対象（上位）", ""))
    lines.extend(
        [
            f"- {_code(entity.entity_name)} / {_code(entity.vcenter_name)} / "
            f"{entity.item_count} 件 / {_time(entity.first_seen_utc, zone)}"
            for entity in highlights.top_entities
        ]
        or ["なし"]
    )
    lines.extend(("", "### 初めて出た種別", ""))
    lines.extend(
        [
            f"- {_code(event.event_type)} / {event.count} 件 / {_time(event.first_seen_utc, zone)}"
            f" / 最大スコア {event.max_score}"
            for event in highlights.new_event_types
        ]
        or ["なし"]
    )
    lines.extend(("", "### 初めて警告以上で出たログの型", ""))
    lines.extend(_new_log_patterns_highlight(result, zone))
    lines.extend(("", "### 検知した障害パターン", ""))
    for pattern in highlights.detected_patterns:
        parts = [_code(pattern.title), _code(pattern.entity_name or pattern.entity_moid)]
        if pattern.subject == "device":
            parts.append(_code(pattern.device_id) if pattern.device_id else "デバイスを特定できません")
        parts.extend((
            f"{_time(pattern.first_utc, zone)} ～ {_time(pattern.last_utc, zone)}",
            f"{pattern.event_count} 件",
            _code(pattern.description),
        ))
        lines.append("- " + " / ".join(parts))
    if not highlights.detected_patterns:
        lines.append("判定の無い結果と、判定して 0 件だった結果は見分けられません。")
        lines.append("")
    if highlights.detected_patterns_total > len(highlights.detected_patterns):
        lines.append(f"- 総数: {highlights.detected_patterns_total} 件")
    omitted = "、".join(_code(pattern) for pattern in highlights.omitted_patterns)
    lines.append(f"- 判定を省いたパターン: {omitted or '-'}")
    lines.extend(("", "### 構成変更", ""))
    lines.extend(_config_changes_highlight(result, zone))
    return lines


def _new_log_patterns_highlight(result: IncidentTimelineViewResponse, zone: ZoneInfo) -> list[str]:
    highlights = result.highlights
    if highlights.log_patterns_backfill_pending:
        return ["台帳の埋め戻し中のため、判定していません。"]
    patterns = highlights.new_log_patterns
    if patterns is None:
        return ["判定していません（この機能の前に保存した結果、または種別にログが無い）"]

    lines = [
        f"- {_time(pattern.first_utc, zone)} / {_code(pattern.template)} / {_code(pattern.log_kind)}"
        f" / {_code(pattern.vcenter_name)} / {'、'.join(_code(host) for host in pattern.hosts)}"
        f" / {pattern.count} 件 / 最大重大度 {severity_name(pattern.max_severity_rank)}"
        for pattern in patterns
    ] or ["なし"]
    if highlights.new_log_patterns_total > len(patterns):
        lines.append(f"- 総数 {highlights.new_log_patterns_total} 件")
    warmups = highlights.log_patterns_warming_up
    if warmups:
        lines.extend(("", "慣らしの期間にあるため判定から除いた出どころ（最大 20 件）"))
        for source in warmups:
            end = _time(source.warmup_ends_at, zone) if source.warmup_ends_at else "開始時刻の記録なし"
            lines.append(
                f"- {_code(source.vcenter_name)} / {_code(source.host or source.source_id)}"
                f" / {_code(source.log_kind)} / {end}"
            )
        remaining = highlights.log_patterns_warming_up_total - len(warmups)
        if remaining > 0:
            lines.append(f"- ほかに {remaining} 件")
    if highlights.new_log_patterns_out_of_retention:
        lines.extend(("", "ログの保持期間で行が削除された型は、一覧に出ないことがあります。"))
    return lines


def _config_diff_value(value: JsonValue) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _config_changes_highlight(result: IncidentTimelineViewResponse, zone: ZoneInfo) -> list[str]:
    highlights = result.highlights
    changes = highlights.config_changes
    if changes is None:
        return ["判定していません（この機能の前に保存した結果、または種別にイベントが無い）"]

    lines = []
    for change in changes:
        time = _time(change.first_utc, zone)
        if change.first_utc != change.last_utc:
            time += f" ～ {_time(change.last_utc, zone)}"
        users = "、".join(_code(name) for name in change.user_names) or "-"
        lines.append(
            f"- {time} / {_code(change.label)} / {_code(change.entity_name or change.entity_moid)}"
            f" / {_code(change.vcenter_name)} / {users} / {change.event_count} 件"
        )
        diffs = change.diffs or []
        first_success = change.diffs_first_success_at
        for diff in diffs:
            target = (diff.entity_name or diff.entity_moid) if change.diffs_multiple_targets else None
            label = " / ".join(
                _code(part)
                for part in (target, diff.category_label, diff.element_label, diff.attribute_label)
                if part
            )
            old = _code(_config_diff_value(diff.old_value))
            new = _code(_config_diff_value(diff.new_value))
            if diff.attribute is None:
                change_text = f"追加 {new}" if diff.old_value is None else f"削除 {old}"
            else:
                change_text = f"{old} → {new}"
            reset_note = ""
            if first_success is not None and to_utc(diff.observed_at) < to_utc(first_success):
                reset_note = " 記録をやり直す前の値"
            lines.append(
                f"  - {label}: {change_text}"
                f"（{_time(diff.changed_after, zone)} から {_time(diff.observed_at, zone)} の間）{reset_note}"
            )
        if change.diffs_total > len(diffs):
            lines.append(f"  - ほか {change.diffs_total - len(diffs)} 件")
    if not changes:
        lines.append("なし")
    counts = "、".join(
        f"{_code(CONFIG_CHANGE_LABELS.get(kind, kind))} {count} 件"
        for kind, count in highlights.config_change_counts.items()
    )
    lines.extend((
        "",
        f"- 種類ごとの件数: {counts or '-'}",
        f"- 表示の上限を超えた件数: {max(0, highlights.config_changes_total - len(changes))} 件",
        f"- 読み込み上限による打ち切り: {'あり' if highlights.config_changes_truncated else 'なし'}",
    ))
    return lines


def _notable_items(
    items: list[IncidentTimelineViewItem],
) -> list[IncidentTimelineViewItem]:
    warnings: list[int] = []
    info: list[int] = []
    for index, item in enumerate(items):
        (info if item.level == "info" else warnings).append(index)

    chosen: list[int] = []
    for group in (warnings, info):
        remaining = _NOTABLE_LIMIT - len(chosen)
        if remaining == 0:
            break
        selected = select_without_anchor([items[index] for index in group], remaining)
        chosen.extend(group[index] for index in selected)
    return [items[index] for index in sorted(chosen)]


def _notable_table(
    result: IncidentTimelineViewResponse, zone: ZoneInfo, export_format: ExportFormat
) -> list[str]:
    items = _notable_items(result.items)
    count = len(result.items)
    if result.truncated:
        added_count = result.config_change_items_shown
        displayed = f"表示した {count - added_count} 件"
        if added_count:
            displayed += f"と構成変更の追加 {added_count} 件"
        included = (
            "を ZIP の items.csv に入れた"
            if export_format == "zip"
            else "は ZIP の出力にある"
        )
        summary = (
            f"総数 {result.total_items} 件のうち、{displayed}{included}。"
            f"報告書の表はそのうち {len(items)} 件"
        )
    else:
        included = (
            "ZIP の items.csv にある" if export_format == "zip" else "ZIP の出力にある"
        )
        if result.config_change_items_truncated:
            summary = f"一覧の {count} 件のうち {len(items)} 件。一覧に表示した行は {included}"
        else:
            summary = f"全 {count} 件のうち {len(items)} 件。全件は {included}"
    if result.config_change_items_truncated:
        summary += "。打ち切った構成変更の行は CSV に含まれません"
    rows = [
        summary,
        "",
        "| 時刻 | 種類 | レベル | vCenter | 対象 | 表題 | 詳細 | 件数 | スコア |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        vcenter, entity, title, detail = (
            _code(value, limit=_CELL_LIMIT, cell=True)
            for value in (
                item.vcenter_name,
                item.entity_name or item.ref.entity_moid,
                item.title,
                item.detail,
            )
        )
        rows.append(
            f"| {_time(item.timestamp_utc, zone)} | {_SOURCES[item.kind]} | {item.level} | "
            f"{vcenter} | {entity} | {title} | {detail} | {item.count} | {_number(item.score)} |"
        )
    return rows


def _report(
    result: IncidentTimelineViewResponse,
    request: ViewRequest | None,
    export_format: ExportFormat,
    zone: ZoneInfo,
    exported_at: datetime,
    aggregated_at: datetime | None,
    snapshot: SavedSnapshotSource | None,
    current_vcenter_name: str | None,
) -> str:
    period = f"{_time(result.from_utc, zone)} ～ {_time(result.to_utc, zone)}"
    lines = [
        f"# インシデントタイムライン 調査資料（{period}）",
        "",
        f"- 出力した時刻: {_time(exported_at, zone)}",
    ]
    if snapshot is None:
        lines.extend(
            (
                f"- 出典: 今の表示（集計した時刻: {_time(aggregated_at, zone)}）",
                "- 表示の後に集計し直したので、画面と件数が違うことがある",
            )
        )
    else:
        lines.append(
            f"- 出典: 保存した結果（ID: {_code(str(snapshot.id))}、保存の時刻: {_time(snapshot.saved_at, zone)}）"
        )
    lines.extend(("", "上限付きの要約です。サポートバンドルの代わりにはなりません。"))
    lines.extend(
        ("", "## 条件", "", *_conditions(result, request, zone, current_vcenter_name))
    )
    if snapshot is not None:
        lines.extend(("", "## メモ", "", _note(snapshot.operator_note)))
    lines.extend(("", "## 概要", "", *_overview(result)))
    lines.extend(("", "## ハイライト", "", *_highlights(result, zone)))
    lines.extend(
        ("", "## 注目すべき出来事", "", *_notable_table(result, zone, export_format))
    )
    return "\n".join(lines) + "\n"


def _csv(columns: tuple[str, ...], rows: Iterable[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def _items_csv(result: IncidentTimelineViewResponse, zone: ZoneInfo) -> bytes:
    def rows() -> Iterable[dict[str, object]]:
        for item in result.items:
            fields = item.model_dump(exclude={"ref", "timestamp_utc", "end_utc"})
            fields["kind_label"] = _SOURCES[item.kind]
            fields.update(item.ref.model_dump(exclude={"peak_at_utc"}))
            for key, value in (
                ("timestamp", item.timestamp_utc),
                ("end", item.end_utc),
                ("peak_at", item.ref.peak_at_utc),
            ):
                fields[key], fields[f"{key}_utc_offset"] = _csv_time(value, zone)
            for key in _TEXT_COLUMNS:
                if isinstance(fields[key], str):
                    fields[key] = neutralize_csv_formula(fields[key])
            fields["time_zone"] = zone.key
            yield fields

    return _csv(_ITEM_COLUMNS, rows())


def _overview_csv(result: IncidentTimelineViewResponse, zone: ZoneInfo) -> bytes:
    def rows() -> Iterable[dict[str, object]]:
        for bucket in result.overview:
            start, offset = _csv_time(bucket.bucket_start_utc, zone)
            yield {
                **bucket.model_dump(exclude={"bucket_start_utc"}),
                "bucket_start": start,
                "bucket_start_utc_offset": offset,
                "time_zone": zone.key,
            }

    return _csv(
        ("bucket_start", "bucket_start_utc_offset", *OVERVIEW_FIELDS, "time_zone"),
        rows(),
    )


def _with_cut_details(
    result: IncidentTimelineViewResponse,
) -> IncidentTimelineViewResponse:
    def cut(item: IncidentTimelineViewItem) -> IncidentTimelineViewItem:
        if item.detail is None or len(item.detail) <= DETAIL_MAX_CHARS:
            return item
        return item.model_copy(
            update={"detail": item.detail[:DETAIL_MAX_CHARS] + _DETAIL_CUT_MARK}
        )

    highlights = result.highlights
    if highlights.first_signal is not None:
        highlights = highlights.model_copy(
            update={"first_signal": cut(highlights.first_signal)}
        )
    return result.model_copy(
        update={"items": [cut(item) for item in result.items], "highlights": highlights}
    )


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _conditions_json(
    result: IncidentTimelineViewResponse,
    request: ViewRequest | None,
    zone: ZoneInfo,
    exported_at: datetime,
    aggregated_at: datetime | None,
    snapshot: SavedSnapshotSource | None,
) -> bytes:
    view_request = (
        request.model_dump(mode="json", by_alias=True)
        if request is not None
        else {
            "from": to_utc(result.from_utc).isoformat().replace("+00:00", "Z"),
            "to": to_utc(result.to_utc).isoformat().replace("+00:00", "Z"),
            "detail": _CONDITIONS_UNREADABLE,
        }
    )
    data = {
        "view_request": view_request,
        "source": "snapshot" if snapshot is not None else "current",
        "exported_at": exported_at.isoformat(),
        "time_zone": zone.key,
    }
    if snapshot is not None:
        data.update(
            snapshot_id=str(snapshot.id),
            saved_at=to_utc(snapshot.saved_at).isoformat(),
            operator_note=snapshot.operator_note,
        )
    elif aggregated_at is not None:
        data["aggregated_at"] = aggregated_at.isoformat()
    return _json(data)


def generate_investigation_export(
    result: IncidentTimelineViewResponse,
    request: ViewRequest | None,
    export_format: ExportFormat,
    zone: ZoneInfo,
    exported_at: datetime,
    *,
    snapshot: SavedSnapshotSource | None = None,
    aggregated_at: datetime | None = None,
    current_vcenter_name: str | None = None,
) -> tuple[str, bytes]:
    """出典と結果から、添付ファイルの名前と中身を作る。"""
    local = to_utc(exported_at).astimezone(zone)
    filename = f"timeline-{local:%Y%m%d-%H%M%S}"
    if snapshot is not None:
        filename += f"-{str(snapshot.id)[:8]}"
    else:
        result = _with_cut_details(result)

    if export_format == "zip":
        result_json = _json(result.model_dump(mode="json"))
        if snapshot is None and len(result_json) > RESULT_MAX_BYTES:
            raise ExportResultTooLarge

    report = _report(
        result,
        request,
        export_format,
        zone,
        exported_at,
        aggregated_at,
        snapshot,
        current_vcenter_name,
    ).encode("utf-8")
    if export_format == "md":
        return f"{filename}.md", report

    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:

        def write(name: str, content: bytes) -> None:
            info = ZipInfo(name, date_time=local.timetuple()[:6])
            archive.writestr(info, content, compress_type=ZIP_DEFLATED)

        write("report.md", report)
        write("items.csv", _items_csv(result, zone))
        write("overview.csv", _overview_csv(result, zone))
        write("result.json", result_json)
        write(
            "conditions.json",
            _conditions_json(
                result, request, zone, exported_at, aggregated_at, snapshot
            ),
        )
    return f"{filename}.zip", output.getvalue()
