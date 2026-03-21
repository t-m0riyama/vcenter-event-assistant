"""Datastore capacity samples from Datastore.summary (blocking, pyVmomi)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from pyVmomi import vim

logger = logging.getLogger(__name__)


def datastore_space_rows_from_datastores(
    datastores: Iterable[Any],
    *,
    sampled_at: datetime,
) -> list[dict[str, Any]]:
    """
    Build metric sample dicts for datastore used % and used bytes from summary.

    Skips datastores with missing or zero capacity.
    """
    rows: list[dict[str, Any]] = []
    for ds in datastores:
        try:
            summary = ds.summary
            cap = getattr(summary, "capacity", None)
            free = getattr(summary, "freeSpace", None)
            if cap is None or float(cap) <= 0:
                continue
            cap_f = float(cap)
            free_f = float(free or 0)
            used_f = cap_f - free_f
            pct = (used_f / cap_f) * 100.0 if cap_f else 0.0
            moid = ds._moId
            name = ds.name
            rows.append(
                {
                    "sampled_at": sampled_at,
                    "entity_type": "Datastore",
                    "entity_moid": moid,
                    "entity_name": name,
                    "metric_key": "datastore.space.used_pct",
                    "value": round(pct, 4),
                }
            )
            rows.append(
                {
                    "sampled_at": sampled_at,
                    "entity_type": "Datastore",
                    "entity_moid": moid,
                    "entity_name": name,
                    "metric_key": "datastore.space.used_bytes",
                    "value": round(used_f, 4),
                }
            )
        except Exception:
            logger.warning("datastore summary metrics skipped for datastore=%s", getattr(ds, "name", "?"), exc_info=True)
    return rows


def sample_datastore_metrics_blocking(si: Any) -> list[dict[str, Any]]:
    """Return flattened metric sample dicts for all datastores in the inventory."""
    now = datetime.now(timezone.utc)
    content = si.RetrieveContent()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.Datastore], True)
    try:
        return datastore_space_rows_from_datastores(view.view, sampled_at=now)
    finally:
        view.Destroy()
