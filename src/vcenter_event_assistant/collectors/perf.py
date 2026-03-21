"""Host quick-stats based performance samples (blocking)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pyVmomi import vim

from vcenter_event_assistant.collectors.connection import connect_vcenter, disconnect


def _iter_hosts(si) -> list[Any]:
    content = si.RetrieveContent()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
    try:
        return list(view.view)
    finally:
        view.Destroy()


def _host_metrics(host) -> list[dict[str, Any]]:
    qs = host.summary.quickStats
    hw = host.summary.hardware
    num_cores = host.hardware.cpuInfo.numCpuCores if host.hardware.cpuInfo else 1
    cpu_mhz_used = float(qs.overallCpuUsage or 0)
    mem_mb_used = float(qs.overallMemoryUsage or 0)
    mem_total_mb = float(host.hardware.memorySize or 0) / (1024 * 1024)
    cpu_mhz_total = float(hw.cpuMhz or 0) * float(num_cores)
    cpu_pct = (cpu_mhz_used / cpu_mhz_total * 100.0) if cpu_mhz_total else 0.0
    mem_pct = (mem_mb_used / mem_total_mb * 100.0) if mem_total_mb else 0.0

    moid = host._moId
    name = host.name
    now = datetime.now(timezone.utc)
    samples = [
        {
            "sampled_at": now,
            "entity_type": "HostSystem",
            "entity_moid": moid,
            "entity_name": name,
            "metric_key": "host.cpu.usage_pct",
            "value": round(cpu_pct, 2),
        },
        {
            "sampled_at": now,
            "entity_type": "HostSystem",
            "entity_moid": moid,
            "entity_name": name,
            "metric_key": "host.mem.usage_pct",
            "value": round(mem_pct, 2),
        },
    ]
    return samples


def sample_hosts_blocking(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
) -> list[dict[str, Any]]:
    """Return flattened metric sample dicts for all hosts."""
    si = connect_vcenter(host=host, port=port, username=username, password=password)
    try:
        rows: list[dict[str, Any]] = []
        for h in _iter_hosts(si):
            rows.extend(_host_metrics(h))
        return rows
    finally:
        disconnect(si)
