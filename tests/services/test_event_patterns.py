"""計画書の判定例と、対象ごとの集約を確かめる。"""

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import ceil
from uuid import UUID

import pytest

from vcenter_event_assistant.services.event_patterns.definitions import BUILTIN_PATTERNS, PatternStep
from vcenter_event_assistant.services.event_patterns.detection import PatternEvent, detect_pattern
from vcenter_event_assistant.device_ids import extract_storage_device_id

T0 = datetime(2026, 3, 22, tzinfo=timezone.utc)
VC = UUID(int=1)
PATTERNS = {p.id: p for p in BUILTIN_PATTERNS}
REPEAT = replace(PATTERNS["host-conn-flapping"], steps=(PatternStep(frozenset({"A"})),))
SEQUENCE = replace(
    PATTERNS["host-reconnect-failed"],
    steps=(PatternStep(frozenset({"A"})), PatternStep(frozenset({"B"}))),
)


def _event(event_id, minute, kind="A", moid="host-1", name=None, **kwargs):
    return PatternEvent(event_id, VC, T0 + timedelta(minutes=minute), kind, moid, name, "HostSystem", **kwargs)


@pytest.mark.parametrize(("gap", "expected"), [(0.5, [(1, 2)]), (300, [(1, 2)]), (301, [(1,), (2,)])])
def test_pdl_collapses_same_device_from_first_occurrence(gap, expected):
    first = _event(1, 0, "esx.problem.scsi.device.state.permanentloss", message="Device naa.A012 has been removed or is permanently inaccessible")
    second = _event(2, gap / 60, "esx.problem.psastor.device.state.permanentloss", message="Device naa.a012 has been removed or is permanently inaccessible")
    detections = detect_pattern(PATTERNS["pdl"], [second, first])
    assert [d.event_ids for d in detections] == expected
    assert detections[0].device_id == "naa.A012"


def test_builtin_event_pattern_definitions():
    assert len(PATTERNS) == len(BUILTIN_PATTERNS) == 8
    for pattern in BUILTIN_PATTERNS:
        assert re.fullmatch(r"[a-z0-9-]{1,32}", pattern.id)
        assert 1 <= pattern.within_minutes <= 1440
        assert pattern.description and pattern.title
        assert all(step.event_types and all(step.event_types) for step in pattern.steps)
        if pattern.kind == "repeat":
            assert len(pattern.steps) == 1
            assert pattern.min_count is not None and pattern.min_count >= 2
            assert pattern.collapse_seconds >= 0
        elif pattern.kind == "sequence":
            assert len(pattern.steps) >= 2
            assert pattern.min_count is None and pattern.collapse_seconds == 0
        else:
            assert pattern.kind == "occurrence"
            assert len(pattern.steps) == 1 and pattern.min_count is None
            assert pattern.collapse_seconds >= 1
            assert pattern.within_minutes == ceil(pattern.collapse_seconds / 60)
        assert pattern.subject == ("device" if pattern.id == "pdl" else None)
        if pattern.id == "ha-failover":
            assert pattern.target.roles == {"computeResource"}
            assert pattern.target.entity_types == {"ClusterComputeResource"}
        else:
            assert pattern.target.roles == {"host", "object", "managedObject"}
            assert pattern.target.entity_types == {"HostSystem"}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Device t10.ATA___X has been removed or is permanently inaccessible", "t10.ATA___X"),
        ("Device mpx.vmhba1:C0:T0:L0 has been removed or is permanently inaccessible", "mpx.vmhba1:C0:T0:L0"),
        ("Device naa.A(X) has been removed or is permanently inaccessible. naa.B", None),
        ("Device t10.ATA___X(Y) has been removed or is permanently inaccessible. naa.B", None),
        ("Device t10.ATA WITH SPACE has been removed or is permanently inaccessible", None),
        ("Device naa.123 disk A has been removed or is permanently inaccessible", None),
        ("Device t10.ATA WITH SPACE has been removed or is permanently inaccessible. Affected datastores: naa.other", None),
        ("(vim.event.EventEx) {fullFormattedMessage = 'Disk naa.a'}", "naa.a"),
        ("Disk eui.001", "eui.001"),
        ("Disk naa.a, NAA.A", "naa.a"),
        ("Disk naa.a, eui.1", None),
        ("Disk ds-naa.a", None),
        ("Disk naa.a.", "naa.a"),
        ("Disk naa.a. Next", "naa.a"),
        ("Disk naa.a, affected datastores", "naa.a"),
        ("Disk naa.", None),
        ("Disk naa." + "a" * 124, "naa." + "a" * 124),
        ("Disk naa." + "a" * 125, None),
        ("Disk naa.a(abc)", None),
        ("Disk naa.a/abc", None),
        ("Disk naa.a+abc", None),
        ("Disk naa.a/naa.b", None),
        ("Disk naa.a(naa.b)", None),
        ("Disk naa.a+naa.b", None),
        ("Disk (naa.a)", "naa.a"),
        ("Disk naa.a/abc, eui.01", "eui.01"),
        ("失ったデバイス naa.a。", "naa.a"),
        ("失ったデバイス（naa.a）", "naa.a"),
    ],
)
def test_device_id_extraction(message, expected):
    assert extract_storage_device_id(message) == expected


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
