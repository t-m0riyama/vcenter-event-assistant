from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from pyVmomi import vim, vmodl
from pyVmomi.VmomiSupport import UnknownManagedMethod
from vcenter_event_assistant_plugin_api import limits
from vcenter_event_assistant_plugin_api.testing import (
    FakeServiceInstance,
    failing_connection,
    run_collect,
)
from vcenter_event_assistant_plugin_api.vmware import event_entities

from vcenter_event_assistant.collectors.tasks import (
    fetch_tasks_from_connection_blocking,
    normalize_task,
)
from vcenter_event_assistant.mocks import mock_collectors
from vcenter_event_assistant.plugins.builtin import TasksCollector
from vcenter_event_assistant.rules.notable import score_event

STARTED = datetime(2026, 11, 24, 1, 2, 3, tzinfo=timezone.utc)
COMPLETED = STARTED + timedelta(seconds=12.3)


def _task(**overrides) -> vim.TaskInfo:
    values = {
        "key": "task-123",
        "task": vim.Task("task-123"),
        "descriptionId": "VirtualMachine.powerOn",
        "state": vim.TaskInfo.State.success,
        "cancelled": False,
        "cancelable": False,
        "reason": vim.TaskReasonUser(userName="operator"),
        "queueTime": STARTED,
        "startTime": STARTED,
        "completeTime": COMPLETED,
        "eventChainId": 456,
    }
    return vim.TaskInfo(**(values | overrides))


@pytest.mark.parametrize(
    ("state", "cancelled", "fault", "result", "severity", "outcome"),
    [
        ("success", False, None, "success", "info", "succeeded"),
        ("success", True, None, "success", "info", "succeeded"),
        ("error", False, None, "error", "error", "failed"),
        (
            "error",
            True,
            vim.fault.InvalidPowerState(),
            "canceled",
            "warning",
            "was canceled",
        ),
        (
            "error",
            False,
            vmodl.fault.RequestCanceled(),
            "canceled",
            "warning",
            "was canceled",
        ),
    ],
)
def test_normalize_task_result(state, cancelled, fault, result, severity, outcome):
    row = normalize_task(_task(state=state, cancelled=cancelled, error=fault))

    assert row is not None
    assert row["vmware_key"] == 123
    assert row["occurred_at"] == COMPLETED
    assert row["event_type"] == f"task.{result}.VirtualMachine.powerOn"
    assert row["severity"] == severity
    assert row["message"] == (
        f"Task VirtualMachine.powerOn {outcome} "
        "(started: 2026-11-24T01:02:03+00:00, duration: 12.3s, reason: user)"
    )


@pytest.mark.parametrize(
    "state", [vim.TaskInfo.State.running, vim.TaskInfo.State.queued]
)
def test_normalize_task_ignores_incomplete_states(state):
    assert normalize_task(_task(state=state)) is None


@pytest.mark.parametrize(
    ("method", "operation"),
    [
        (vim.VirtualMachine.PowerOn, "PowerOn"),
        (UnknownManagedMethod("FutureOperation"), "FutureOperation"),
        (None, "unknown"),
    ],
)
def test_normalize_task_falls_back_to_method_name(method, operation):
    row = normalize_task(_task(descriptionId="", name=method))

    assert row is not None
    assert row["event_type"] == f"task.success.{operation}"


@pytest.mark.parametrize("extra", [0, 1])
def test_normalize_task_event_type_length_limit(extra):
    prefix = "task.success."
    operation = "x" * (limits.MAX_EVENT_TYPE - len(prefix) + extra)
    row = normalize_task(_task(descriptionId=operation))

    assert row is not None
    assert row["event_type"] == prefix + ("unknown" if extra else operation)


@pytest.mark.parametrize(
    ("overrides", "warning"),
    [
        ({"key": "malformed-task-123"}, "task key"),
        ({"key": "task--5"}, "task key"),
        ({"key": "task-abc"}, "task key"),
        ({"key": f"task-{limits.VMWARE_KEY_MAX + 1}"}, "task key"),
        ({"key": "task-" + "9" * 5000}, "task key"),
        ({"completeTime": None}, "missing completeTime"),
    ],
)
def test_normalize_task_skips_invalid_rows(overrides, warning, caplog):
    assert normalize_task(_task(**overrides)) is None
    assert any(
        record.levelname == "WARNING" and warning in record.message
        for record in caplog.records
    )


def test_normalize_task_without_start_time_uses_aware_completion_time():
    row = normalize_task(
        _task(startTime=None, completeTime=COMPLETED.replace(tzinfo=None))
    )

    assert row is not None
    assert row["occurred_at"] == COMPLETED
    assert row["message"] == "Task VirtualMachine.powerOn succeeded (reason: user)"


@pytest.mark.parametrize(
    ("reason", "label", "user_name"),
    [
        (vim.TaskReasonUser(userName="operator"), "user", "operator"),
        (vim.TaskReasonSchedule(name="daily run"), "schedule (daily run)", None),
        (vim.TaskReasonSchedule(), "schedule", None),
        (vim.TaskReasonAlarm(alarmName="CPU load"), "alarm (CPU load)", None),
        (vim.TaskReasonAlarm(), "alarm", None),
        (vim.TaskReasonSystem(), "system", None),
    ],
)
def test_normalize_task_reason(reason, label, user_name):
    row = normalize_task(_task(reason=reason))

    assert row is not None
    assert row["message"].endswith(f"reason: {label})")
    assert row["user_name"] == user_name


@pytest.mark.parametrize(
    ("fault_fields", "failure"),
    [
        (
            {
                "msg": "Wrong state",
                "faultMessage": [vmodl.LocalizableMessage(message="Fallback")],
            },
            "Wrong state [InvalidPowerState]",
        ),
        (
            {
                "faultMessage": [
                    vmodl.LocalizableMessage(),
                    vmodl.LocalizableMessage(message="Fallback"),
                ]
            },
            "Fallback [InvalidPowerState]",
        ),
        ({}, "InvalidPowerState"),
    ],
)
def test_normalize_task_fault_message_fallbacks(fault_fields, failure):
    row = normalize_task(
        _task(state="error", error=vim.fault.InvalidPowerState(**fault_fields))
    )

    assert row is not None
    assert row["message"].startswith(f"Task VirtualMachine.powerOn failed: {failure} (")


def test_normalize_task_preserves_primary_and_child_entities():
    info = _task(
        entity=vim.VirtualMachine("vm-10"),
        entityName="failover-vm",
        locked=[vim.HostSystem("host-20"), vim.Datastore("datastore-30")],
        result=vim.VirtualMachine("vm-40"),
    )
    row = normalize_task(info)

    assert row is not None
    assert (row["entity_name"], row["entity_type"], row["entity_moid"]) == (
        "failover-vm",
        "VirtualMachine",
        "vm-10",
    )
    assert row["entities"] == event_entities(info)
    assert {(e.role, e.entity_moid, e.is_primary) for e in row["entities"]} == {
        ("entity", "vm-10", True),
        ("locked", "host-20", False),
        ("locked", "datastore-30", False),
        ("result", "vm-40", False),
    }
    assert "failover-vm" not in row["message"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (456, 456),
        (limits.VMWARE_KEY_MIN, limits.VMWARE_KEY_MIN),
        (limits.VMWARE_KEY_MAX, limits.VMWARE_KEY_MAX),
        (limits.VMWARE_KEY_MIN - 1, None),
        (limits.VMWARE_KEY_MAX + 1, None),
    ],
)
def test_normalize_task_chain_id(value, expected):
    row = normalize_task(_task(eventChainId=value))

    assert row is not None
    assert row["chain_id"] == expected


@pytest.mark.parametrize("since", [None, STARTED, STARTED.replace(tzinfo=None)])
def test_fetch_tasks_filters_by_completion_and_reads_all_pages(since, caplog):
    si = MagicMock()
    create = si.RetrieveContent.return_value.taskManager.CreateCollectorForTasks
    collector = create.return_value
    collector.ReadNextTasks.side_effect = [
        [_task(key="task-124")],
        [_task(completeTime=STARTED), _task(key="task-125", completeTime=None)],
        [],
    ]

    before = datetime.now(timezone.utc)
    rows, max_ts = fetch_tasks_from_connection_blocking(si, since=since)
    after = datetime.now(timezone.utc)

    assert [row["vmware_key"] for row in rows] == [124, 123]
    assert max_ts == COMPLETED
    spec = create.call_args.args[0]
    assert spec.state == [vim.TaskInfo.State.success, vim.TaskInfo.State.error]
    assert spec.time.timeType == vim.TaskFilterSpec.TimeOption.completedTime
    assert before <= spec.time.endTime <= after
    assert spec.time.beginTime == (
        STARTED if since else spec.time.endTime - timedelta(days=1)
    )
    assert collector.ReadNextTasks.call_args_list == [call(500)] * 3
    collector.DestroyCollector.assert_called_once_with()
    assert "max_pages" not in caplog.text


def test_fetch_tasks_warns_at_page_limit(caplog):
    si = MagicMock()
    collector = (
        si.RetrieveContent.return_value.taskManager.CreateCollectorForTasks.return_value
    )
    collector.ReadNextTasks.return_value = [_task()]

    rows, _ = fetch_tasks_from_connection_blocking(si, since=None, max_pages=2)

    assert len(rows) == 2
    assert collector.ReadNextTasks.call_args_list == [call(500)] * 2
    collector.DestroyCollector.assert_called_once_with()
    assert any(
        record.levelname == "WARNING" and "max_pages=2" in record.message
        for record in caplog.records
    )


def test_fetch_tasks_destroys_collector_when_read_fails():
    si = MagicMock()
    collector = (
        si.RetrieveContent.return_value.taskManager.CreateCollectorForTasks.return_value
    )
    collector.ReadNextTasks.side_effect = RuntimeError("read failed")

    with pytest.raises(RuntimeError, match="read failed"):
        fetch_tasks_from_connection_blocking(si, since=None)

    collector.DestroyCollector.assert_called_once_with()


async def test_tasks_collector_advances_cursor_to_latest_completion():
    now = datetime.now(timezone.utc)
    previous = now - timedelta(hours=2)
    completed = now - timedelta(hours=1)
    started = previous - timedelta(days=1)
    si = FakeServiceInstance()
    manager = MagicMock()
    collector = manager.CreateCollectorForTasks.return_value
    collector.ReadNextTasks.side_effect = [
        [
            _task(startTime=started, completeTime=completed),
            _task(
                key="task-124",
                startTime=previous,
                completeTime=completed - timedelta(minutes=1),
            ),
        ],
        [],
    ]
    # FakeServiceInstance は呼び出しごとに新しい content を返す。
    with patch.object(
        si, "RetrieveContent", return_value=SimpleNamespace(taskManager=manager)
    ):
        batch = await run_collect(
            TasksCollector(), connection=si, previous_cursor=previous.isoformat()
        )

    spec = manager.CreateCollectorForTasks.call_args.args[0]
    assert spec.time.beginTime == previous - timedelta(seconds=1)
    assert batch.events[0].occurred_at == completed
    assert batch.next_cursor == completed.isoformat()


async def test_tasks_collector_mock_results_and_stable_keys(monkeypatch):
    now = datetime(2026, 11, 24, 1, 5, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(mock_collectors, "datetime", FrozenDateTime)
    kwargs = {
        "mock_mode": True,
        "connection": failing_connection(AssertionError("must not connect")),
    }
    batch = await run_collect(TasksCollector(), **kwargs)
    assert [event.event_type for event in batch.events] == [
        "task.success.VirtualMachine.powerOn",
        "task.error.VirtualMachine.powerOn",
        "task.canceled.VirtualMachine.migrate",
    ]
    assert [
        score_event(
            event_type=event.event_type, message=event.message, severity=event.severity
        ).score
        for event in batch.events
    ] == [0, 50, 20]
    assert len({event.vmware_key for event in batch.events}) == 3

    now += timedelta(minutes=10)
    repeated = await run_collect(
        TasksCollector(), previous_cursor=batch.next_cursor, **kwargs
    )
    assert repeated.events == batch.events

    now += timedelta(minutes=30)
    later = await run_collect(
        TasksCollector(), previous_cursor=batch.next_cursor, **kwargs
    )
    assert len(later.events) == 3
    assert {event.vmware_key for event in later.events}.isdisjoint(
        event.vmware_key for event in batch.events
    )
    assert later.events[-1].occurred_at == batch.events[-1].occurred_at + timedelta(
        minutes=30
    )
