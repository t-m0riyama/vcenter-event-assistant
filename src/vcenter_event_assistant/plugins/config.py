"""TOML-backed collector configuration."""

from __future__ import annotations

import os
import re
import tomllib
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
    if isinstance(config_values, dict) and (config_values or overrides.get("replace_config")):
        values = (
            dict(merged.get("config", {}))
            if isinstance(merged.get("config"), dict)
            else {}
        )
        if overrides.get("replace_config"):
            values = {}
        values.update(config_values)
        merged["config"] = values
    return merged


def collector_environment_prefix(plugin_id: str) -> str:
    """Legacy environment variable prefix."""
    normalized = re.sub(r"[^A-Z0-9]", "_", plugin_id.upper())
    return f"VEA_COLLECTOR__{normalized}__"


def collector_environment(
    plugin_ids: set[str],
    environ: Mapping[str, str] = os.environ,
) -> tuple[dict[str, dict[str, str]], dict[str, frozenset[str]]]:
    """Resolve settings once for an installed set, without sharing ambiguous legacy values."""
    values: dict[str, dict[str, str]] = {plugin_id: {} for plugin_id in plugin_ids}
    conflicts: dict[str, frozenset[str]] = {}
    legacy = {plugin_id: collector_environment_prefix(plugin_id) for plugin_id in plugin_ids}
    exact = {
        plugin_id.encode("utf-8").hex().upper(): plugin_id
        for plugin_id in plugin_ids
    }
    for name, value in environ.items():
        if not name.startswith("VEA_COLLECTOR__"):
            continue
        matches = {
            plugin_id for plugin_id, prefix in legacy.items()
            if name.startswith(prefix) and len(name) > len(prefix)
        }
        if len(matches) > 1:
            conflicts[name] = frozenset(matches)
        elif matches:
            plugin_id = matches.pop()
            values[plugin_id][name[len(legacy[plugin_id]):].lower()] = value

    for name, value in environ.items():
        if not name.startswith("VEA_COLLECTOR_ID__"):
            continue
        prefix, separator, key = name[len("VEA_COLLECTOR_ID__"):].partition("__")
        plugin_id = exact.get(prefix)
        if plugin_id is not None and separator and key:
            values[plugin_id][key.lower()] = value
    return values, conflicts


def collector_env_locked_fields(fields: tuple[str, ...]) -> list[str]:
    """Only the common fields can be updated through the collector settings API."""
    return sorted(set(fields).intersection(_DB_OVERRIDE_FIELDS))


def apply_collector_environment(
    raw: Mapping[str, Any], environment: Mapping[str, str]
) -> dict[str, Any]:
    """Overlay common and plugin-specific values from a deterministic env prefix."""
    merged = dict(raw)
    values = (
        dict(merged.get("config", {}))
        if isinstance(merged.get("config", {}), dict)
        else {}
    )
    for key, value in environment.items():
        if key == "enabled":
            merged["enabled"] = value.strip().lower() in {"1", "true", "yes", "on"}
        elif key in {"interval_seconds", "timeout_seconds"}:
            merged[key] = value
        else:
            values[key] = value
    merged["config"] = values
    return merged
