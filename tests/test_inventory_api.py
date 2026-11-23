"""インベントリの影響範囲と収集状態の HTTP API を検証する。"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.collectors.inventory import (
    InventoryObjectData,
    InventoryObservation,
)
from vcenter_event_assistant.db.base import Base
from vcenter_event_assistant.db.models import (
    EventEntity,
    EventRecord,
    InventorySyncRun,
    InventorySyncState,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.services.inventory import persist_inventory
from vcenter_event_assistant.settings import get_settings

IMPACT = "/api/inventory/impact"
STATUS = "/api/inventory/status"
NOW = utcnow().replace(microsecond=0)
T0 = NOW - timedelta(hours=2)
T1 = T0 + timedelta(minutes=10)
T2 = T1 + timedelta(minutes=10)

OBJECTS = {
    "h1": InventoryObjectData("HostSystem", "esx-1"),
    "h2": InventoryObjectData("HostSystem", "esx-2"),
    "vm": InventoryObjectData("VirtualMachine", "guest"),
    "c1": InventoryObjectData("ClusterComputeResource", "cluster-1"),
    "c2": InventoryObjectData("ClusterComputeResource", "cluster-2"),
    "ds": InventoryObjectData("Datastore", "datastore"),
    "n1": InventoryObjectData("Network", "normal"),
    "n2": InventoryObjectData("DistributedVirtualPortgroup", "distributed"),
    "n3": InventoryObjectData("OpaqueNetwork", "opaque"),
}
RELATIONS = {
    ("vm_host", "vm", "h1"),
    ("host_cluster", "h1", "c1"),
    ("host_cluster", "h2", "c1"),
    ("vm_datastore", "vm", "ds"),
    ("host_datastore", "h1", "ds"),
    *{("vm_network", "vm", net) for net in ("n1", "n2", "n3")},
    *{("host_network", "h1", net) for net in ("n1", "n2", "n3")},
}


@pytest.fixture(params=["sqlite", "postgres"])
async def inventory_session(request, tmp_path):
    if request.param == "postgres":
        url = os.environ.get("VEA_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("VEA_TEST_POSTGRES_URL must point to a dedicated test DB")
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'inventory.db'}"
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            if request.param == "postgres":
                await conn.execute(text("DROP SCHEMA public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
def inventory_settings():
    return get_settings().model_copy(
        update={
            "auth_enabled": False,
            "event_retention_days": 7,
            "scheduler_enabled": True,
            "inventory_sync_enabled": False,
            "inventory_sync_interval_seconds": 600,
            "inventory_sync_timeout_seconds": 90,
        }
    )


@pytest.fixture
async def inventory_client(inventory_session, inventory_settings, open_client):
    app = create_app()

    async def session():
        yield inventory_session

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_app_settings] = lambda: inventory_settings
    async with open_client(None, app=app) as client:
        yield client


async def add_center(session, name="inventory", *, enabled=True):
    center = VCenter(
        name=name, host="vc.example", username="u", password="p", is_enabled=enabled
    )
    session.add(center)
    await session.flush()
    return center.id


async def observe(session, vc, at, objects, relations, *, instance="vc"):
    await persist_inventory(
        session,
        vc,
        InventoryObservation(instance, objects, relations, set()),
        observed_at=at,
        started_at=at,
    )
    await session.flush()


async def event_entity(session, vc, at, moid, entity_type, *, key):
    session.add(
        EventRecord(
            vcenter_id=vc,
            occurred_at=at,
            event_type="VmEvent",
            vmware_key=key,
            entities=[
                EventEntity(
                    vcenter_id=vc,
                    entity_moid=moid,
                    entity_type=entity_type,
                    role="vm",
                    position=0,
                    is_primary=True,
                )
            ],
        )
    )
    await session.flush()


async def impact(client, vc, moid, at=None, **params):
    if at is not None:
        params["at"] = at.isoformat()
    return await client.get(
        IMPACT, params={"vcenter_id": str(vc), "entity_moid": moid, **params}
    )


def utc_field(body, key):
    return datetime.fromisoformat(body[key]) if body[key] is not None else None


def groups(body):
    return {
        group["relation"]: [item["moid"] for item in group["items"]]
        for group in body["groups"]
    }


async def test_inventory_impact_groups_by_target_type(
    inventory_client, inventory_session
):
    vc = await add_center(inventory_session)
    await observe(inventory_session, vc, T0, OBJECTS, RELATIONS)
    expected = {
        "h1": {
            "cluster": ["c1"],
            "vms": ["vm"],
            "datastores": ["ds"],
            "networks": ["n2", "n1", "n3"],
        },
        "vm": {
            "hosts": ["h1"],
            "cluster": ["c1"],
            "datastores": ["ds"],
            "networks": ["n2", "n1", "n3"],
        },
        "c1": {"hosts": ["h1", "h2"], "vms": ["vm"]},
        "ds": {"hosts": ["h1"], "vms": ["vm"]},
        **{net: {"hosts": ["h1"], "vms": ["vm"]} for net in ("n1", "n2", "n3")},
    }
    await event_entity(inventory_session, vc, T1, "vm", "Folder", key=1)
    for moid, expected_groups in expected.items():
        response = await impact(inventory_client, vc, moid, T0)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["target"] == {
            "moid": moid,
            "entity_type": OBJECTS[moid].entity_type,
            "name": OBJECTS[moid].name,
        }
        assert groups(body) == expected_groups
        for group in body["groups"]:
            assert group["total"] == len(group["items"])
            for item in group["items"]:
                assert item == {
                    "moid": item["moid"],
                    "entity_type": OBJECTS[item["moid"]].entity_type,
                    "name": OBJECTS[item["moid"]].name,
                    "removed": False,
                }


async def test_inventory_impact_boundaries_ha_and_host_cluster_moves(
    inventory_client, inventory_session
):
    vc = await add_center(inventory_session)
    await observe(inventory_session, vc, T0, OBJECTS, RELATIONS)
    moved_vm = RELATIONS - {("vm_host", "vm", "h1")} | {("vm_host", "vm", "h2")}
    await observe(inventory_session, vc, T1, OBJECTS, moved_vm)
    moved_host = moved_vm - {("host_cluster", "h2", "c1")} | {
        ("host_cluster", "h2", "c2")
    }
    await observe(inventory_session, vc, T2, OBJECTS, moved_host)
    before_ha = T1 - timedelta(microseconds=1)
    assert groups((await impact(inventory_client, vc, "h1", T0)).json())["vms"] == [
        "vm"
    ]
    assert groups((await impact(inventory_client, vc, "h1", before_ha)).json())[
        "vms"
    ] == ["vm"]
    assert groups((await impact(inventory_client, vc, "h1", T1)).json())["vms"] == []
    assert groups((await impact(inventory_client, vc, "h2", T1)).json())["vms"] == [
        "vm"
    ]
    assert groups((await impact(inventory_client, vc, "vm", T1)).json())["cluster"] == [
        "c1"
    ]
    assert groups((await impact(inventory_client, vc, "vm", T2)).json())["cluster"] == [
        "c2"
    ]
    assert groups((await impact(inventory_client, vc, "c1", T1)).json())["vms"] == [
        "vm"
    ]
    assert groups((await impact(inventory_client, vc, "c1", T2)).json())["vms"] == []
    assert groups((await impact(inventory_client, vc, "c2", T2)).json()) == {
        "hosts": ["h2"],
        "vms": ["vm"],
    }


async def test_inventory_impact_status_precedence_and_observations(
    inventory_client, inventory_session
):
    session = inventory_session
    vc = await add_center(session)
    other = await add_center(session, "other")
    empty = await add_center(session, "empty")
    session.add(InventorySyncState(vcenter_id=other, last_error="failed"))
    await event_entity(session, vc, T1, "event-only", "Folder", key=1)
    await event_entity(session, vc, T0, "event-only", "HostSystem", key=2)
    await event_entity(session, other, T2, "event-only", "HostSystem", key=1)
    initial = {key: value for key, value in OBJECTS.items() if key != "h2"}
    await observe(session, vc, T0, initial, {("vm_host", "vm", "h1")})
    late = T0 + timedelta(hours=1)
    await observe(
        session,
        vc,
        late,
        {key: value for key, value in OBJECTS.items() if key != "h1"},
        {("vm_host", "vm", "h2")},
    )

    assert (await impact(inventory_client, uuid4(), "h1")).status_code == 404
    cases = [
        (vc, "event-only", T0 - timedelta(seconds=1), "unsupported_type"),
        (vc, "missing", T0 - timedelta(seconds=1), "not_recorded"),
        (vc, "missing", T0, "unknown_target"),
        (other, "event-only", T0, "not_recorded"),
        (empty, "h1", T0, "not_recorded"),
        (vc, "h2", T0 + timedelta(minutes=21), "absent_at_time"),
        (vc, "h2", late, "ok"),
        (vc, "h1", late, "absent_at_time"),
        (vc, "vm", T0 + timedelta(minutes=20), "ok"),
        (vc, "vm", T0 + timedelta(minutes=20, microseconds=1), "stale"),
    ]
    for center, moid, at, expected in cases:
        response = await impact(inventory_client, center, moid, at)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == expected, (moid, at, body)
        if expected in {"unsupported_type", "not_recorded", "unknown_target"}:
            assert body["groups"] == []
        if expected in {"absent_at_time", "stale"}:
            assert body["groups"]
            assert utc_field(body, "observed_before") == (late if at == late else T0)
            assert utc_field(body, "observed_after") == (None if at == late else late)
        if expected == "stale":
            assert groups(body)["hosts"] == ["h1"]
        if expected == "unsupported_type":
            assert body["target"] == {
                "moid": "event-only",
                "entity_type": "Folder",
                "name": "event-only",
            }

    await event_entity(session, vc, T1, "supported", "HostSystem", key=3)
    assert (await impact(inventory_client, vc, "supported", late)).json()[
        "status"
    ] == "unknown_target"
    run = await session.scalar(
        InventorySyncRun.__table__.select()
        .with_only_columns(InventorySyncRun.id)
        .where(
            InventorySyncRun.vcenter_id == vc,
            InventorySyncRun.observed_at == T0,
        )
    )
    await session.delete(await session.get(InventorySyncRun, run))
    await session.flush()
    missing_prev = (await impact(inventory_client, vc, "vm", T0)).json()
    assert missing_prev["status"] == "stale"
    assert missing_prev["observed_before"] is None
    assert utc_field(missing_prev, "observed_after") == late
    assert groups(missing_prev)["hosts"] == ["h1"]


async def test_inventory_impact_at_default_offset_and_future(
    inventory_client, inventory_session
):
    vc = await add_center(inventory_session)
    await observe(inventory_session, vc, T0, OBJECTS, RELATIONS)
    offset_time = T0.astimezone(timezone(timedelta(hours=9)))
    assert (
        utc_field((await impact(inventory_client, vc, "vm", offset_time)).json(), "at")
        == T0
    )

    before = utcnow()
    default = (await impact(inventory_client, vc, "vm")).json()
    assert before <= utc_field(default, "at") <= utcnow()
    before = utcnow()
    future = (await impact(inventory_client, vc, "vm", NOW + timedelta(days=2))).json()
    assert before <= utc_field(future, "at") <= utcnow()

    # 最初の成功直後に時計が戻っても、at を省いて直近の構成を参照できる。
    rollback_vc = await add_center(inventory_session, "rollback")
    last_success = NOW + timedelta(days=1)
    await observe(inventory_session, rollback_vc, last_success, OBJECTS, RELATIONS)
    rollback = (await impact(inventory_client, rollback_vc, "vm")).json()
    assert rollback["status"] == "ok"
    assert utc_field(rollback, "at") == last_success
    assert groups(rollback)["hosts"] == ["h1"]

    await observe(inventory_session, vc, last_success, OBJECTS, set())
    future = (await impact(inventory_client, vc, "vm", NOW + timedelta(days=2))).json()
    assert utc_field(future, "at") == last_success
    assert utc_field(future, "observed_before") == last_success
    assert groups(future)["hosts"] == []
    assert (
        await inventory_client.get(
            IMPACT,
            params={
                "vcenter_id": str(vc),
                "entity_moid": "vm",
                "at": "0001-01-01T00:00:00+01:00",
            },
        )
    ).status_code == 422


async def test_inventory_impact_group_and_change_limits(
    inventory_client, inventory_session
):
    vc = await add_center(inventory_session)
    mixed_names = {201: "B", 202: "A", 203: "z", 204: "a"}
    guests = {
        f"vm-{i:03}": InventoryObjectData("VirtualMachine", mixed_names.get(i, "b"))
        for i in reversed(range(205))
    }
    edges = {("vm_host", moid, "h1") for moid in guests}
    await observe(inventory_session, vc, T0, {"h1": OBJECTS["h1"]}, set())
    await observe(inventory_session, vc, T1, {"h1": OBJECTS["h1"], **guests}, edges)
    await observe(inventory_session, vc, T2, {"h1": OBJECTS["h1"]}, set())
    result = (
        await impact(
            inventory_client,
            vc,
            "h1",
            T1,
            **{"from": T0.isoformat(), "to": T2.isoformat()},
        )
    ).json()
    vms = next(group for group in result["groups"] if group["relation"] == "vms")
    assert vms["total"] == 205
    assert [item["moid"] for item in vms["items"]] == ["vm-202", "vm-204", "vm-201"] + [
        f"vm-{i:03}" for i in range(197)
    ]
    assert all(item["removed"] for item in vms["items"])
    changes = result["changes"]
    assert changes["total"] == 410
    assert len(changes["items"]) == 200
    assert all(
        utc_field(item, "at") == T1
        and item["action"] == "opened"
        and item["kind"] == "vm_host"
        for item in changes["items"]
    )


async def test_inventory_impact_changes_trim_retention_and_match_only_target(
    inventory_client, inventory_session
):
    vc = await add_center(inventory_session)
    old = NOW - timedelta(days=8)
    edges = {("vm_host", "vm", "h1"), ("host_cluster", "h2", "c2")}
    await observe(inventory_session, vc, old, OBJECTS, edges)
    await observe(inventory_session, vc, T0, OBJECTS, set())
    await observe(inventory_session, vc, T1, OBJECTS, {("vm_host", "vm", "h2")})
    before = utcnow() - timedelta(days=7)
    bounds = {
        "from": old.isoformat(),
        "to": T1.astimezone(timezone(timedelta(hours=9))).isoformat(),
    }
    body = (await impact(inventory_client, vc, "vm", T1, **bounds)).json()
    assert before <= utc_field(body, "recorded_since") <= utcnow() - timedelta(days=7)
    changes = body["changes"]
    assert changes["total"] == 2
    assert [
        (utc_field(row, "at"), row["kind"], row["action"], row["other"]["moid"])
        for row in changes["items"]
    ] == [(T0, "vm_host", "closed", "h1"), (T1, "vm_host", "opened", "h2")]
    clipped = (
        await impact(
            inventory_client, vc, "vm", T1, **{**bounds, "from": T0.isoformat()}
        )
    ).json()["changes"]
    assert clipped == {"total": 1, "items": [changes["items"][1]]}
    assert utc_field(clipped["items"][0], "at") == T1
    history = (await impact(inventory_client, vc, "vm", old)).json()
    assert history["status"] == "not_recorded"
    assert history["groups"] == []


async def test_inventory_impact_validates_query(inventory_client, inventory_session):
    vc = await add_center(inventory_session)
    assert (await impact(inventory_client, "invalid-uuid", "vm")).status_code == 422
    for bounds in (
        {"from": T0.isoformat()},
        {"to": T1.isoformat()},
        {"from": T1.isoformat(), "to": T0.isoformat()},
    ):
        response = await impact(inventory_client, vc, "vm", **bounds)
        assert response.status_code == 422, response.text
    equal = await impact(
        inventory_client, vc, "vm", **{"from": T0.isoformat(), "to": T0.isoformat()}
    )
    assert equal.status_code == 200
    assert equal.json()["changes"] == {"total": 0, "items": []}


async def test_inventory_impact_uses_moid_for_empty_names(
    inventory_client, inventory_session
):
    vc = await add_center(inventory_session)
    objects = {
        "h1": OBJECTS["h1"],
        "vm-a": InventoryObjectData("VirtualMachine", ""),
        "vm-b": InventoryObjectData("VirtualMachine", "before"),
    }
    edges = {("vm_host", "vm-a", "h1"), ("vm_host", "vm-b", "h1")}
    await observe(inventory_session, vc, T0, objects, edges)
    host = (await impact(inventory_client, vc, "h1", T0)).json()
    vms = next(group for group in host["groups"] if group["relation"] == "vms")
    assert [(item["moid"], item["name"]) for item in vms["items"]] == [
        ("vm-b", "before"),
        ("vm-a", "vm-a"),
    ]
    vm = (await impact(inventory_client, vc, "vm-a", T0)).json()
    assert vm["target"]["name"] == "vm-a"


async def test_inventory_impact_changes_skip_closures_from_previous_instance(
    inventory_client, inventory_session
):
    vc = await add_center(inventory_session)
    await observe(inventory_session, vc, T0, OBJECTS, {("vm_host", "vm", "h1")})
    await observe(
        inventory_session,
        vc,
        T1,
        OBJECTS,
        {("vm_host", "vm", "h2")},
        instance="replacement",
    )
    body = (
        await impact(
            inventory_client,
            vc,
            "vm",
            T1,
            **{"from": T0.isoformat(), "to": T1.isoformat()},
        )
    ).json()
    assert utc_field(body, "recorded_since") == T1
    assert body["changes"] == {"total": 0, "items": []}


async def test_inventory_status_returns_configuration_and_empty_vcenters(
    inventory_client, inventory_session
):
    vc = await add_center(inventory_session)
    empty = await add_center(inventory_session, "empty", enabled=False)
    inventory_session.add(
        InventorySyncState(
            vcenter_id=vc,
            instance_uuid="hidden",
            first_success_at=T0,
            last_started_at=T2,
            last_success_at=T1,
            last_failure_at=T2,
            last_error="failed",
            last_warning="count decreased",
            last_warning_at=T1,
            object_count=10,
            relation_count=7,
        )
    )
    await inventory_session.flush()
    response = await inventory_client.get(STATUS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {
        key: body[key] for key in ("enabled", "interval_seconds", "timeout_seconds")
    } == {
        "enabled": False,
        "interval_seconds": 600,
        "timeout_seconds": 90,
    }
    missing, present = body["vcenters"]
    times = {
        "first_success_at": T0,
        "last_started_at": T2,
        "last_success_at": T1,
        "last_failure_at": T2,
        "last_warning_at": T1,
    }
    counters = {
        "last_error": "failed",
        "last_warning": "count decreased",
        "object_count": 10,
        "relation_count": 7,
    }
    assert missing == {
        "vcenter_id": str(empty),
        "vcenter_name": "empty",
        "is_enabled": False,
        **dict.fromkeys(times),
        **dict.fromkeys(counters),
    }
    assert present == {
        "vcenter_id": str(vc),
        "vcenter_name": "inventory",
        "is_enabled": True,
        **{key: at.isoformat().replace("+00:00", "Z") for key, at in times.items()},
        **counters,
    }


@pytest.mark.parametrize("scheduler_enabled", [False, True])
async def test_inventory_status_enabled_requires_scheduler(
    inventory_client, inventory_settings, scheduler_enabled
):
    inventory_settings.inventory_sync_enabled = True
    inventory_settings.scheduler_enabled = scheduler_enabled
    response = await inventory_client.get(STATUS)
    assert response.status_code == 200
    assert response.json()["enabled"] is scheduler_enabled


async def test_inventory_viewer_and_anonymous_permissions(viewer_client, anon_client):
    async with session_scope() as session:
        vc = await add_center(session)
        session.add(
            InventorySyncState(
                vcenter_id=vc, last_error="failed", last_warning="warning"
            )
        )
    assert (await impact(viewer_client, vc, "vm")).status_code == 200
    assert (await impact(anon_client, vc, "vm")).status_code == 401
    assert (await anon_client.get(STATUS)).status_code == 401
    response = await viewer_client.get(STATUS)
    assert response.status_code == 200
    assert response.json()["vcenters"][0]["last_error"] == "failed"
    assert response.json()["vcenters"][0]["last_warning"] == "warning"
