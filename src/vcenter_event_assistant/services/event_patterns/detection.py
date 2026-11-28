"""イベントの並びから障害パターンを判定する純関数。"""

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from vcenter_event_assistant.device_ids import extract_storage_device_id
from vcenter_event_assistant.services.event_patterns.definitions import EventPattern


@dataclass(frozen=True, slots=True)
class PatternEvent:
    event_id: int
    vcenter_id: UUID
    occurred_at: datetime
    event_type: str
    entity_moid: str
    entity_name: str | None
    entity_type: str | None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class PatternDetection:
    pattern: EventPattern
    vcenter_id: UUID
    entity_moid: str
    entity_name: str | None
    entity_type: str | None
    first_utc: datetime
    last_utc: datetime
    event_ids: tuple[int, ...]
    device_id: str | None = None


def detect_pattern(pattern: EventPattern, rows: Iterable[PatternEvent]) -> list[PatternDetection]:
    """対象ごとに重複を除き、時刻とイベント ID の順で判定する。"""
    grouped: dict[tuple[UUID, str] | tuple[UUID, str, int, str | int], dict[int, PatternEvent]]
    grouped = defaultdict(dict)
    for row in rows:
        target: tuple[UUID, str] | tuple[UUID, str, int, str | int] = (row.vcenter_id, row.entity_moid)
        if pattern.subject == "device":
            device = extract_storage_device_id(row.message)
            target = (*target, 0, device.lower()) if device is not None else (*target, 1, row.event_id)
        # 同じイベントと対象では、問い合わせが優先した先頭の行を残す。
        grouped[target].setdefault(row.event_id, row)

    detections: list[PatternDetection] = []
    for target in sorted(grouped):
        events = sorted(grouped[target].values(), key=lambda e: (e.occurred_at, e.event_id))
        if pattern.kind == "repeat":
            matches = _repeat(pattern, events)
        elif pattern.kind == "sequence":
            matches = _sequence(pattern, events)
        else:
            matches = _occurrence(pattern, events)
        for matched in matches:
            first, last = matched[0], matched[-1]
            detections.append(PatternDetection(
                pattern, last.vcenter_id, last.entity_moid, last.entity_name, last.entity_type,
                first.occurred_at, last.occurred_at, tuple(e.event_id for e in matched),
                extract_storage_device_id(first.message) if pattern.subject == "device" else None,
            ))
    return detections


def _occurrence(pattern: EventPattern, events: list[PatternEvent]) -> Iterator[list[PatternEvent]]:
    collapse = timedelta(seconds=pattern.collapse_seconds)
    matched: list[PatternEvent] = []
    for event in events:
        if event.event_type not in pattern.steps[0].event_types:
            continue
        if matched and event.occurred_at - matched[0].occurred_at > collapse:
            yield matched
            matched = []
        matched.append(event)
    if matched:
        yield matched


def _repeat(pattern: EventPattern, events: list[PatternEvent]) -> Iterator[list[PatternEvent]]:
    assert pattern.min_count is not None
    candidates = [e for e in events if e.event_type in pattern.steps[0].event_types]
    collapse = timedelta(seconds=pattern.collapse_seconds)
    counted: list[int] = []
    for index, event in enumerate(candidates):
        if collapse and counted and event.occurred_at - candidates[counted[-1]].occurred_at <= collapse:
            continue
        counted.append(index)

    # まとめの末尾までを取れるよう、次の回の開始位置を終端に使う。
    counted.append(len(candidates))
    width = timedelta(minutes=pattern.within_minutes)
    left = 0
    merged: list[tuple[int, int]] = []
    for right, index in enumerate(counted[:-1]):
        while candidates[index].occurred_at - candidates[counted[left]].occurred_at > width:
            left += 1
        if right - left + 1 < pattern.min_count:
            continue
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], right)
        else:
            merged.append((left, right))
    for first, last in merged:
        yield candidates[counted[first]:counted[last + 1]]


def _sequence(pattern: EventPattern, events: list[PatternEvent]) -> Iterator[list[PatternEvent]]:
    # 起点が失敗しても、次の段を二分探索で探し直せるようにする。
    first_step, *middle_steps, final_step = [
        [i for i, event in enumerate(events) if event.event_type in step.event_types]
        for step in pattern.steps
    ]
    width = timedelta(minutes=pattern.within_minutes)
    times = [event.occurred_at for event in events]
    last_used = -1
    for start in first_step:
        if start <= last_used:
            continue
        deadline = times[start] + width
        matched = [start]
        for step in middle_steps:
            next_pos = bisect_right(step, matched[-1])
            if next_pos == len(step) or times[step[next_pos]] > deadline:
                break
            matched.append(step[next_pos])
        else:
            next_pos = bisect_right(final_step, matched[-1])
            end_pos = bisect_right(final_step, bisect_right(times, deadline) - 1)
            if next_pos >= end_pos:
                continue
            matched.extend(final_step[next_pos:end_pos])
            last_used = matched[-1]
            yield [events[i] for i in matched]
