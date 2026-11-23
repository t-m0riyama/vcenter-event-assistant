"""計画書の判定例と、対象ごとの集約を確かめる。"""

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from vcenter_event_assistant.services.event_patterns.definitions import BUILTIN_PATTERNS, PatternStep
from vcenter_event_assistant.services.event_patterns.detection import PatternEvent, detect_pattern

T0 = datetime(2026, 3, 22, tzinfo=timezone.utc)
VC = UUID(int=1)
PATTERNS = {p.id: p for p in BUILTIN_PATTERNS}
REPEAT = replace(PATTERNS["host-conn-flapping"], steps=(PatternStep(frozenset({"A"})),))
SEQUENCE = replace(
    PATTERNS["host-reconnect-failed"],
    steps=(PatternStep(frozenset({"A"})), PatternStep(frozenset({"B"}))),
)


def _event(event_id, minute, kind="A", moid="host-1", name=None):
    return PatternEvent(event_id, VC, T0 + timedelta(minutes=minute), kind, moid, name, "HostSystem")


def test_builtin_event_pattern_definitions():
    assert len(PATTERNS) == len(BUILTIN_PATTERNS) == 7
    for pattern in BUILTIN_PATTERNS:
        assert re.fullmatch(r"[a-z0-9-]{1,32}", pattern.id)
        assert 1 <= pattern.within_minutes <= 1440
        assert pattern.description and pattern.title
        assert all(step.event_types and all(step.event_types) for step in pattern.steps)
        if pattern.kind == "repeat":
            assert len(pattern.steps) == 1
            assert pattern.min_count is not None and pattern.min_count >= 2
            assert pattern.collapse_seconds >= 0
        else:
            assert pattern.kind == "sequence" and len(pattern.steps) >= 2
            assert pattern.min_count is None and pattern.collapse_seconds == 0
        if pattern.id == "ha-failover":
            assert pattern.target.roles == {"computeResource"}
            assert pattern.target.entity_types == {"ClusterComputeResource"}
        else:
            assert pattern.target.roles == {"host", "object", "managedObject"}
            assert pattern.target.entity_types == {"HostSystem"}


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        ((0, 20, 40), [(1, 2, 3)]),
        ((0, 20, 40, 70, 90), [(1, 2, 3, 4, 5)]),
        ((0, 20, 61), []),
        ((0, 30, 60), [(1, 2, 3)]),
        ((0, 1, 2, 75, 76, 77), [(1, 2, 3), (4, 5, 6)]),
    ],
)
def test_repeat_windows(minutes, expected):
    events = [_event(i, m) for i, m in enumerate(minutes, 1)]
    assert [d.event_ids for d in detect_pattern(REPEAT, events)] == expected


@pytest.mark.parametrize(
    ("collapse", "seconds", "expected"),
    [
        (0, (0, 0, 0), [(1, 2, 3)]),
        (1, (0, 0, 1), []),
        (1, (0, 1, 1.5, 2, 3), [(1, 2, 3, 4, 5)]),
        (120, (0, 0, 120, 121), [(1, 2, 3, 4)]),
        (60, (0, 0, 60, 61, 122), [(1, 2, 3, 4, 5)]),
    ],
)
def test_repeat_collapse_boundary(collapse, seconds, expected):
    pattern = replace(REPEAT, collapse_seconds=collapse, min_count=2 if collapse == 120 else 3)
    events = [_event(i, s / 60) for i, s in enumerate(seconds, 1)]
    assert [d.event_ids for d in detect_pattern(pattern, events)] == expected


@pytest.mark.parametrize(
    ("specs", "expected"),
    [
        (((1, 0, "A"), (2, 25, "A"), (3, 40, "B")), [(2, 3)]),
        (((1, 0, "A"), (2, 30, "B")), [(1, 2)]),
        (((1, 0, "B"), (2, 10, "A")), []),
        (((2, 0, "A"), (1, 0, "B")), []),
        (((2, 0, "B"), (1, 0, "A")), [(1, 2)]),
        (((1, 0, "A"), (2, 5, "B"), (3, 40, "A"), (4, 45, "B")), [(1, 2), (3, 4)]),
        (((1, 0, "A"), (2, 10, "B"), (3, 14, "A"), (4, 30, "B"), (5, 31, "B")), [(1, 2, 4)]),
    ],
)
def test_sequence_order_and_last_step(specs, expected):
    assert [d.event_ids for d in detect_pattern(SEQUENCE, [_event(*s) for s in specs])] == expected


def test_sequence_with_three_steps_uses_earliest_middle_event():
    pattern = replace(SEQUENCE, steps=(*SEQUENCE.steps, PatternStep(frozenset({"C"}))))
    events = [_event(i, i, kind) for i, kind in enumerate("ABBCACABC", 1)]
    assert [d.event_ids for d in detect_pattern(pattern, events)] == [(1, 2, 4, 6, 9)]


def test_same_event_counts_once_per_target():
    events = [_event(i, i, moid=moid) for i in (1, 2, 3) for moid in ("host-1", "host-1", "host-2")]
    detections = detect_pattern(REPEAT, events)
    assert [(d.entity_moid, d.event_ids) for d in detections] == [
        ("host-1", (1, 2, 3)),
        ("host-2", (1, 2, 3)),
    ]
    assert detections == detect_pattern(REPEAT, events)
