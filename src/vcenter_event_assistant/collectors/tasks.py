"""Collect completed vCenter tasks using an existing pyVmomi session."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from pyVmomi import vim, vmodl
from pyVmomi.VmomiSupport import ManagedMethod, UnknownManagedMethod
from vcenter_event_assistant_plugin_api import limits
from vcenter_event_assistant_plugin_api.timeutils import ensure_aware
from vcenter_event_assistant_plugin_api.vmware import event_entities

logger = logging.getLogger(__name__)
_TASK_KEY = re.compile(r"task-([0-9]+)")
_MAX_TASK_KEY_DIGITS = len(str(limits.VMWARE_KEY_MAX))


def fetch_tasks_from_connection_blocking(
    si: Any, *, since: datetime | None, max_pages: int = 100
) -> tuple[list[dict[str, Any]], datetime | None]:
    """Return normalized tasks and the latest completion time in the batch."""
    now = datetime.now(timezone.utc)
    spec = vim.TaskFilterSpec(
        time=vim.TaskFilterSpec.ByTime(
            timeType=vim.TaskFilterSpec.TimeOption.completedTime,
            beginTime=ensure_aware(since)
            if since is not None
            else now - timedelta(days=1),
            endTime=now,
        ),
        state=[vim.TaskInfo.State.success, vim.TaskInfo.State.error],
    )
    collector = si.RetrieveContent().taskManager.CreateCollectorForTasks(spec)
    raw: list[vim.TaskInfo] = []
    try:
        for _ in range(max_pages):
            page = collector.ReadNextTasks(500)
            if not page:
                break
            raw.extend(page)
        else:
            logger.warning(
                "task fetch hit max_pages=%s; more tasks may remain in vCenter",
                max_pages,
            )
    finally:
        collector.DestroyCollector()

    rows = [row for task in raw if (row := normalize_task(task)) is not None]
    return rows, max((row["occurred_at"] for row in rows), default=None)


def _operation(info: vim.TaskInfo) -> str:
    if info.descriptionId:
        return info.descriptionId
    method = info.name
    if isinstance(method, UnknownManagedMethod):
        name = method.name
    elif isinstance(method, ManagedMethod):
        name = getattr(method.info, "name", None)
    else:
        name = None
    return name if isinstance(name, str) and name else "unknown"


def _reason_label(reason: vim.TaskReason) -> str:
    if isinstance(reason, vim.TaskReasonUser):
        return "user"
    if isinstance(reason, vim.TaskReasonSchedule):
        return f"schedule ({reason.name})" if reason.name else "schedule"
    if isinstance(reason, vim.TaskReasonAlarm):
        return f"alarm ({reason.alarmName})" if reason.alarmName else "alarm"
    return "system"


def _failure_message(fault: vmodl.MethodFault | None) -> str:
    if fault is None:
        return "failed"
    fault_type = type(fault).__name__.rsplit(".", 1)[-1]
    detail = fault.msg or next(
        (item.message for item in fault.faultMessage if item.message), None
    )
    if detail:
        return f"failed: {detail} [{fault_type}]"
    return f"failed: {fault_type}"


def normalize_task(info: vim.TaskInfo) -> dict[str, Any] | None:
    """Map a completed pyVmomi task to an event row."""
    match = _TASK_KEY.fullmatch(info.key or "")
    digits = (match[1].lstrip("0") or "0") if match else ""
    key = int(digits) if 0 < len(digits) <= _MAX_TASK_KEY_DIGITS else None
    if key is None or key > limits.VMWARE_KEY_MAX:
        logger.warning(
            "invalid or out-of-range task key, skipping insert: %r", info.key
        )
        return None
    if info.completeTime is None:
        logger.warning("task missing completeTime, skipping insert: key=%s", info.key)
        return None

    if info.state == vim.TaskInfo.State.success:
        result, severity, outcome = "success", "info", "succeeded"
    elif info.state == vim.TaskInfo.State.error:
        if isinstance(info.error, vmodl.fault.RequestCanceled) or info.cancelled:
            result, severity, outcome = "canceled", "warning", "was canceled"
        else:
            result, severity, outcome = "error", "error", _failure_message(info.error)
    else:
        return None

    operation = _operation(info)
    prefix = f"task.{result}."
    if len(prefix) + len(operation) > limits.MAX_EVENT_TYPE:
        operation = "unknown"
    completed = ensure_aware(info.completeTime)
    details: list[str] = []
    if info.startTime is not None:
        started = ensure_aware(info.startTime)
        duration = (completed - started).total_seconds()
        details.extend(
            (f"started: {started.isoformat()}", f"duration: {duration:.1f}s")
        )
    reason = info.reason
    details.append(f"reason: {_reason_label(reason)}")

    entities = event_entities(info)
    primary = next((item for item in entities if item.is_primary), None)
    chain_id = info.eventChainId
    return {
        "occurred_at": completed,
        "event_type": prefix + operation,
        "message": f"Task {operation} {outcome} ({', '.join(details)})",
        "severity": severity,
        "user_name": reason.userName
        if isinstance(reason, vim.TaskReasonUser)
        else None,
        "entity_name": primary.entity_name if primary is not None else None,
        "entity_type": primary.entity_type if primary is not None else None,
        "entity_moid": primary.entity_moid if primary is not None else None,
        "entities": entities,
        "vmware_key": key,
        "chain_id": chain_id
        if limits.VMWARE_KEY_MIN <= chain_id <= limits.VMWARE_KEY_MAX
        else None,
    }
