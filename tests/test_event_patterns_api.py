"""イベントパターンの定義とタイムラインのハイライトを API で確かめる。"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest
from pyVmomi import vim

from vcenter_event_assistant.db.models import EventEntity, EventRecord, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant_plugin_api.vmware import event_entities

T0 = datetime(2026, 3, 22, tzinfo=timezone.utc)
LOST = "vim.event.HostConnectionLostEvent"
RECONNECT = "vim.event.HostReconnectionFailedEvent"
APD = "esx.problem.storage.apd.start"
TIMEOUT = "esx.problem.storage.apd.timeout"
PDL_SCSI = "esx.problem.scsi.device.state.permanentloss"
PDL_PSASTOR = "esx.problem.psastor.device.state.permanentloss"
LINK = "esx.problem.net.vmnic.linkstate.down"
HA = "vim.event.DasHostFailedEvent"
RESTART = "vim.event.VmRestartedOnAlternateHostEvent"
MIGRATE = "vim.event.VmFailedMigrateEvent"
_KEYS = itertools.count(1)


def _at(m):
    return T0 + timedelta(minutes=m)


async def _vc(name="vc", vid=None):
    async with session_scope() as session:
        vc = VCenter(id=vid or uuid.uuid4(), name=name, host="h", port=443, username="u", password="p")
        session.add(vc)
        return vc.id


def _entity(moid="host-1", role="host", kind="HostSystem", name="ESXi_One", position=0):
    return dict(entity_moid=moid, role=role, entity_type=kind, entity_name=name, position=position, is_primary=False)


async def _seed(vid, specs):
    async with session_scope() as session:
        events = []
        for minute, event_type, entities, *message in specs:
            event = EventRecord(
                vcenter_id=vid, occurred_at=_at(minute), event_type=event_type,
                vmware_key=next(_KEYS), entity_moid="vm-primary", entity_name="Primary VM",
                message=message[0] if message else "",
                entities=[EventEntity(vcenter_id=vid, **entity) for entity in entities],
            )
            session.add(event)
            events.append(event)
        await session.flush()
        return [e.id for e in events]


async def _view(client, **kwargs):
    response = await client.post("/api/incident-timeline/view", json={
        "from": T0.isoformat(), "to": _at(120).isoformat(), "sources": ["event"], **kwargs,
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_pdl_uses_saved_messages_and_the_requested_range(client):
    vid = await _vc()
    host_rows = [_entity(role="object", kind=None, name=None), _entity()]
    apd = [(1, APD, host_rows), (2, TIMEOUT, host_rows), (4, APD, host_rows)]
    await _seed(vid, apd)
    baseline = (await _view(client))["highlights"]["detected_patterns"]
    assert {d["pattern_id"] for d in baseline} == {"apd-repeated", "apd-timeout"}

    first, second, third, other, unknown_a, unknown_b = await _seed(vid, [
        (-310 / 60, PDL_SCSI, host_rows, "Device naa.a has been removed or is permanently inaccessible"),
        (-200 / 60, PDL_PSASTOR, host_rows, "Device naa.a has been removed or is permanently inaccessible"),
        (50 / 60, PDL_SCSI, host_rows, "Device naa.a has been removed or is permanently inaccessible"),
        (50 / 60, PDL_SCSI, host_rows, "Device naa.b has been removed or is permanently inaccessible"),
        (50 / 60, PDL_SCSI, host_rows, ""),
        (50 / 60, PDL_PSASTOR, host_rows, ""),
    ])
    all_detections = (await _view(client, **{"from": _at(-10).isoformat()}))["highlights"]["detected_patterns"]
    assert [d["event_ids"] for d in all_detections if d["device_id"] == "naa.a"] == [[third], [first, second]]
    detections = (await _view(client))["highlights"]["detected_patterns"]
    assert [d for d in detections if d["pattern_id"] != "pdl"] == baseline
    assert [(d["device_id"], d["event_ids"]) for d in detections if d["subject"] == "device"] == [
        (None, [unknown_a]), (None, [unknown_b]), ("naa.a", [second, third]), ("naa.b", [other]),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pattern_id", "types", "minutes", "target", "level"),
    [
        ("host-conn-flapping", [LOST] * 3, [0, 30, 60], _entity(), "error"),
        ("host-reconnect-failed", [LOST, RECONNECT], [0, 30], _entity(), "error"),
        ("apd-timeout", [APD, TIMEOUT], [0, 10], _entity(), "critical"),
        ("apd-repeated", [APD] * 2, [0, 60], _entity(), "error"),
        ("nic-link-flapping", [LINK] * 3, [0, 15, 30], _entity(), "warning"),
        ("ha-failover", [HA, RESTART, "com.vmware.vc.ha.VmRestartedByHAEvent"], [0, 5, 30],
         _entity("domain-c1", "computeResource", "ClusterComputeResource"), "critical"),
        ("ha-failover", ["com.vmware.vc.HA.DasHostFailedEvent", RESTART], [0, 30],
         _entity("domain-c1", "computeResource", "ClusterComputeResource"), "critical"),
        ("vmotion-failures", [MIGRATE] * 3, [0, 30, 60], _entity(), "warning"),
    ],
)
async def test_builtin_event_pattern_detects_real_event_types(client, pattern_id, types, minutes, target, level):
    vid = await _vc()
    ids = await _seed(vid, [(m, t, [target]) for m, t in zip(minutes, types, strict=True)])
    highlights = (await _view(client, min_score=100))["highlights"]
    [detection] = highlights["detected_patterns"]
    assert highlights["detected_patterns_total"] == 1
    assert highlights["omitted_patterns"] == []
    assert detection["pattern_id"] == pattern_id
    assert detection["level"] == level
    assert detection["event_ids"] == ids
    assert detection["event_count"] == len(ids)
    assert detection["vcenter_id"] == str(vid) and detection["vcenter_name"] == "vc"
    assert detection["entity_moid"] == target["entity_moid"]
    assert detection["entity_name"] == target["entity_name"]
    assert detection["entity_type"] == target["entity_type"]
    assert datetime.fromisoformat(detection["first_utc"]) == _at(minutes[0])
    assert datetime.fromisoformat(detection["last_utc"]) == _at(minutes[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shape", [
        "object", "host", "managedObject", "untyped_host", "untyped_vm", "uppercase_prefix", "typed_vm",
        "object_and_named_host",
    ],
)
async def test_event_pattern_uses_eventex_shapes_from_plugin_api(client, shape):
    host = vim.HostSystem("host-1")
    events = {
        "object": vim.event.EventEx(objectId="host-1", objectType=vim.HostSystem),
        "host": vim.event.EventEx(host=vim.event.HostEventArgument(host=host)),
        "managedObject": vim.event.ExtendedEvent(managedObject=host),
        "untyped_host": vim.event.EventEx(objectId="host-1"),
        "untyped_vm": vim.event.EventEx(objectId="vm-1"),
        "uppercase_prefix": vim.event.EventEx(objectId="HOST-1"),
        "typed_vm": vim.event.EventEx(objectId="host-1", objectType=vim.VirtualMachine),
        "object_and_named_host": vim.event.EventEx(
            objectId="host-1", host=vim.event.HostEventArgument(host=host, name="esx01"),
        ),
    }
    rows = [asdict(row) for row in event_entities(events[shape])]
    if shape == "object_and_named_host":
        assert [(row["role"], row["entity_name"], row["entity_type"]) for row in rows] == [
            ("object", None, None), ("host", "esx01", "HostSystem"),
        ]
    vid = await _vc()
    await _seed(vid, [(0, APD, rows), (3, TIMEOUT, rows)])
    found = (await _view(client))["highlights"]["detected_patterns"]
    if shape in ("untyped_vm", "uppercase_prefix", "typed_vm"):
        assert found == []
    elif shape == "object_and_named_host":
        [detection] = found
        assert (detection["pattern_id"], detection["entity_name"], detection["entity_type"], detection["event_count"]) == (
            "apd-timeout", "esx01", "HostSystem", 2,
        )
        assert (await _view(client, entity="esx"))["highlights"]["detected_patterns"] == found
    else:
        assert len(rows) == 1
        assert [row["pattern_id"] for row in found] == ["apd-timeout"]
        assert found[0]["entity_name"] is None
        assert found[0]["entity_type"] == rows[0]["entity_type"]


@pytest.mark.asyncio
async def test_event_pattern_period_and_filters(client):
    vid, other = await _vc(), await _vc("other")
    async with session_scope() as session:
        session.add_all(
            EventRecord(
                vcenter_id=vid, occurred_at=_at(m), event_type=LOST, vmware_key=next(_KEYS),
                entity_moid="host-legacy", entity_name="旧ホスト", entity_type="HostSystem",
            )
            for m in (2, 3, 4)
        )
    ids = await _seed(vid, [
        (-61, LOST, [_entity()]), (-60, LOST, [_entity(name="Old")]), (-25, LOST, [_entity(name="Old")]),
        (0, LOST, [_entity(), _entity(role="object")]), (120, LOST, [_entity()]),
        (-50, LOST, [_entity("host-past")]), (-45, LOST, [_entity("host-past")]),
        (-40, LOST, [_entity("host-past")]),
        *[(m, LOST, [_entity(None), _entity("", role="object")]) for m in (2, 4, 5)],
        (6, LOST, [_entity("host-sparse")]), (7, LOST, [_entity("host-other")]),
        (8, LOST, [_entity("host-sparse")]),
        (6, LOST, [_entity("host-late")]), (65, RECONNECT, [_entity("host-late")]),
        (8, TIMEOUT, [_entity("host-reversed")]), (9, APD, [_entity("host-reversed")]),
        (117, APD, [_entity("host-at-end")]), (120, TIMEOUT, [_entity("host-at-end")]),
        (20, APD, [_entity("host-collapsed")]), (20, APD, [_entity("host-collapsed")]),
        (20, LINK, [_entity("host-collapsed")]), (20, LINK, [_entity("host-collapsed")]),
        (25, LINK, [_entity("host-collapsed")]),
    ])
    await _seed(other, [(9, LOST, [_entity("host-sparse")])] + [(i, LOST, [_entity()]) for i in (0, 5, 10)])
    expected = (await _view(client, vcenter_id=str(vid)))["highlights"]["detected_patterns"]
    assert len(expected) == 1
    assert expected[0]["event_ids"] == ids[1:4]
    assert expected[0]["entity_name"] == "ESXi_One"
    assert (await _view(client, vcenter_id=str(vid)))["highlights"]["detected_patterns"] == expected
    assert (await _view(client, entity="xi_on", vcenter_id=str(vid)))["highlights"]["detected_patterns"] == expected
    assert (await _view(client, entity="Old", vcenter_id=str(vid)))["highlights"]["detected_patterns"] == []
    assert (await _view(client, entity="xi%on"))["highlights"]["detected_patterns"] == []
    by_moid = await _view(client, vcenter_id=str(vid), entity_moid="host-1", entity="missing")
    assert by_moid["highlights"]["detected_patterns"] == expected
    assert by_moid["items"] == []
    assert (await _view(client, sources=["alert"]))["highlights"]["detected_patterns"] == []
    unfiltered = (await _view(client))["highlights"]["detected_patterns"]
    assert [row["vcenter_name"] for row in unfiltered] == ["other", "vc"]


@pytest.mark.asyncio
async def test_event_pattern_sort_and_response_limits(client):
    v1 = await _vc("z-vc", uuid.UUID(int=1))
    v2 = await _vc("a-vc", uuid.UUID(int=2))
    for vid in (v1, v2):
        await _seed(vid, [
            (0, APD, [_entity()]), (5, TIMEOUT, [_entity()]),
            (2, APD, [_entity("host-02")]), (5, TIMEOUT, [_entity("host-02")]),
        ])
    ids = await _seed(v1, [(6 + i, LOST, [_entity()]) for i in range(21)])
    await _seed(v1, [(36, APD, [_entity()]), (46, APD, [_entity()])])
    await _seed(v1, [(m, LOST, [_entity("host-2")]) for m in (30, 38, 46)])
    await _seed(v1, [(m, LINK, [_entity(f"host-{i:02}")]) for i in range(30) for m in (50, 55, 60)])
    top = (await _view(client, item_limit=1))["highlights"]
    assert top["detected_patterns_total"] == 37
    assert len(top["detected_patterns"]) == 20
    assert [(d["pattern_id"], d["vcenter_id"], d["entity_moid"]) for d in top["detected_patterns"][:7]] == [
        ("apd-timeout", str(v1), "host-02"), ("apd-timeout", str(v1), "host-1"),
        ("apd-timeout", str(v2), "host-02"), ("apd-timeout", str(v2), "host-1"),
        ("apd-repeated", str(v1), "host-1"), ("host-conn-flapping", str(v1), "host-2"),
        ("host-conn-flapping", str(v1), "host-1"),
    ]
    assert top["detected_patterns"][6]["event_count"] == 21
    assert top["detected_patterns"][6]["event_ids"] == ids[:20]


@pytest.mark.asyncio
async def test_pdl_splits_vcenters_and_hosts_before_applying_the_response_limit(client):
    v1 = await _vc("vc-one", uuid.UUID(int=1))
    v2 = await _vc("vc-two", uuid.UUID(int=2))
    known_devices = [f"naa.d{i:02d}" for i in range(15)]
    first_ids = await _seed(v1, [
        *((1, PDL_PSASTOR, [_entity()], device) for device in reversed(known_devices)),
        (1, PDL_SCSI, [_entity()], ""),
        (1, PDL_PSASTOR, [_entity(role="object", kind=None)], ""),
        (1, PDL_SCSI, [_entity("host-2")], "naa.d00"),
        (1, PDL_SCSI, [_entity(role="vm")], "naa.outside"),
    ])
    second_ids = await _seed(v2, [
        *((1, PDL_SCSI, [_entity()], device) for device in known_devices[:3]),
        (1, PDL_PSASTOR, [_entity()], ""),
    ])
    highlights = (await _view(client))["highlights"]
    assert highlights["detected_patterns_total"] == 22
    assert [
        (d["vcenter_id"], d["entity_moid"], d["device_id"], d["event_ids"])
        for d in highlights["detected_patterns"]
    ] == [
        (str(v1), "host-1", None, [first_ids[15]]),
        (str(v1), "host-1", None, [first_ids[16]]),
        *((str(v1), "host-1", device, [event_id])
          for device, event_id in zip(known_devices, reversed(first_ids[:15]), strict=True)),
        (str(v1), "host-2", "naa.d00", [first_ids[17]]),
        (str(v2), "host-1", None, [second_ids[3]]),
        (str(v2), "host-1", "naa.d00", [second_ids[0]]),
    ]


@pytest.mark.asyncio
async def test_event_pattern_join_row_limit_omits_only_overflowing_pattern(client):
    vid = await _vc()
    # 5000 件 × 2 役割を読み、同じ対象の 5000 件にまとめる。
    await _seed(vid, [(1, LOST, [_entity(), _entity(role="object")])] * 5000)
    await _seed(vid, [(2, APD, [_entity()]), (3, TIMEOUT, [_entity()])])
    top = (await _view(client, min_score=100))["highlights"]
    assert top["omitted_patterns"] == []
    assert top["detected_patterns"][1]["event_count"] == 5000
    await _seed(vid, [(4, LOST, [_entity()])])
    top = (await _view(client, min_score=100))["highlights"]
    assert top["omitted_patterns"] == ["host-conn-flapping", "host-reconnect-failed"]
    assert [d["pattern_id"] for d in top["detected_patterns"]] == ["apd-timeout"]


@pytest.mark.asyncio
async def test_event_patterns_catalog_is_viewer_read_only(viewer_client, anon_client):
    url = "/api/event-patterns"
    response = await viewer_client.get(url)
    assert response.status_code == 200
    patterns = response.json()
    assert [p["id"] for p in patterns] == [
        "host-conn-flapping", "host-reconnect-failed", "apd-timeout",
        "apd-repeated", "nic-link-flapping", "ha-failover", "vmotion-failures",
        "pdl",
    ]
    assert patterns[0] == {
        "id": "host-conn-flapping", "title": "ホストの切断の繰り返し", "description": patterns[0]["description"],
        "level": "error", "kind": "repeat", "steps": [{"event_types": [LOST]}],
        "within_minutes": 60, "min_count": 3, "subject": None,
    }
    assert patterns[0]["description"]
    assert patterns[2]["steps"] == [{"event_types": [APD]}, {"event_types": [TIMEOUT]}]
    assert patterns[2]["min_count"] is None
    pdl = patterns[-1]
    assert (pdl["kind"], pdl["subject"], pdl["within_minutes"], pdl["min_count"]) == (
        "occurrence", "device", 5, None,
    )
    assert pdl["steps"] == [{"event_types": [PDL_PSASTOR, PDL_SCSI]}]
    assert (await viewer_client.post(url, json={})).status_code == 405
    assert (await anon_client.get(url)).status_code == 401
