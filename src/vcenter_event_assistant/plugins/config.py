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


_DB_OVERRIDE_FIELDS = ("enabled", "interval_seconds", "timeout_seconds")


def apply_collector_database_overrides(
    raw: Mapping[str, Any], overrides: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Overlay operator-managed values stored in the database on top of TOML.

    ``None`` は「未設定」を意味し、下位ソース（TOML → manifest 既定値）をそのまま通す。
    """
    merged = dict(raw)
    if not overrides:
        return merged
    for field_name in _DB_OVERRIDE_FIELDS:
        value = overrides.get(field_name)
        if value is not None:
            merged[field_name] = value
    config_values = overrides.get("config_values")
    if isinstance(config_values, dict) and config_values:
        values = (
            dict(merged.get("config", {}))
            if isinstance(merged.get("config"), dict)
            else {}
        )
        values.update(config_values)
        merged["config"] = values
    return merged


def collector_environment_prefix(plugin_id: str) -> str:
    """Deterministic env var prefix for one plugin id."""
    normalized = re.sub(r"[^A-Z0-9]", "_", plugin_id.upper())
    return f"VEA_COLLECTOR__{normalized}__"


def collector_env_locked_fields(plugin_id: str) -> list[str]:
    """Common fields pinned by environment variables for this plugin.

    環境変数は DB 設定より優先されるため、UI はこれらを編集不可として表示する。
    """
    prefix = collector_environment_prefix(plugin_id)
    locked = {
        name[len(prefix) :].lower()
        for name in os.environ
        if name.startswith(prefix)
    }
    return sorted(locked & set(_DB_OVERRIDE_FIELDS))


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
    prefix = collector_environment_prefix(plugin_id)
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
