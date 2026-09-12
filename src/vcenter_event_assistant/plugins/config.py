"""TOML-backed collector configuration."""

from __future__ import annotations

import tomllib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class CollectorConfig:
    enabled: bool
    interval_seconds: int
    timeout_seconds: float = 300.0
    values: Mapping[str, Any] = field(default_factory=dict)


def load_collector_config_file(path: str | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    with Path(path).open("rb") as fh:
        document = tomllib.load(fh)
    raw = document.get("collectors", {})
    if not isinstance(raw, dict):
        raise ValueError("[collectors] must be a TOML table")
    out: dict[str, dict[str, Any]] = {}
    for plugin_id, value in raw.items():
        if not isinstance(value, dict):
            raise ValueError(f"collectors.{plugin_id} must be a TOML table")
        out[str(plugin_id)] = dict(value)
    return out


def apply_collector_environment(
    plugin_id: str, raw: Mapping[str, Any]
) -> dict[str, Any]:
    """Overlay common and plugin-specific values from a deterministic env prefix."""
    merged = dict(raw)
    values = (
        dict(merged.get("config", {}))
        if isinstance(merged.get("config", {}), dict)
        else {}
    )
    normalized = re.sub(r"[^A-Z0-9]", "_", plugin_id.upper())
    prefix = f"VEA_COLLECTOR__{normalized}__"
    for name, value in os.environ.items():
        if not name.startswith(prefix):
            continue
        key = name[len(prefix) :].lower()
        if key == "enabled":
            merged["enabled"] = value.strip().lower() in {"1", "true", "yes", "on"}
        elif key in {"interval_seconds", "timeout_seconds"}:
            merged[key] = value
        else:
            values[key] = value
    merged["config"] = values
    return merged
