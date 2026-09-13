"""Discovery, validation, and immutable snapshots of collector plugins."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from importlib.metadata import entry_points
from types import MappingProxyType
from typing import Mapping

from vcenter_event_assistant_plugin_api import (
    CollectorPlugin,
    MetricDefinition,
)
from vcenter_event_assistant_plugin_api.validation import manifest_error_message

from vcenter_event_assistant.plugins.config import (
    CollectorConfig,
    apply_collector_database_overrides,
    apply_collector_environment,
    load_collector_config_file,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(frozen=True, slots=True)
class CollectorRegistration:
    plugin_id: str
    plugin: CollectorPlugin | None
    source: str
    config: CollectorConfig | None
    status: str
    error: str | None = None


class CollectorRegistry:
    def __init__(
        self, registrations: Mapping[str, CollectorRegistration], *, generation: int = 1
    ):
        self._registrations = MappingProxyType(dict(registrations))
        self.generation = generation

    @property
    def registrations(self) -> Mapping[str, CollectorRegistration]:
        return self._registrations

    def enabled(self) -> tuple[CollectorRegistration, ...]:
        return tuple(r for r in self._registrations.values() if r.status == "enabled")

    def get(self, plugin_id: str) -> CollectorRegistration | None:
        return self._registrations.get(plugin_id)

    def metric_catalog(self) -> tuple[tuple[str, MetricDefinition], ...]:
        return tuple(
            (r.plugin_id, definition)
            for r in self.enabled()
            if r.plugin is not None
            for definition in r.plugin.manifest.metric_definitions
        )


_registry: CollectorRegistry | None = None


def set_collector_registry(registry: CollectorRegistry | None) -> None:
    global _registry
    _registry = registry


def activate_collector_registry(registry: CollectorRegistry) -> None:
    """Atomically replace the active immutable registry snapshot."""
    set_collector_registry(registry)


async def start_collector_registry(registry: CollectorRegistry) -> CollectorRegistry:
    """Start enabled plugins, isolating lifecycle failures into a new snapshot."""
    registrations = dict(registry.registrations)
    for registration in registry.enabled():
        assert registration.plugin is not None
        try:
            await registration.plugin.start()
        except Exception as exc:
            logger.exception(
                "collector plugin start failed plugin_id=%s", registration.plugin_id
            )
            registrations[registration.plugin_id] = replace(
                registration,
                status="failed",
                error=f"start failed: {type(exc).__name__}",
            )
    return CollectorRegistry(registrations, generation=registry.generation)


async def shutdown_collector_registry(registry: CollectorRegistry) -> None:
    """Stop a registry generation without allowing one plugin to block the others."""
    from vcenter_event_assistant.plugins.runtime import drain_collector_runs

    await drain_collector_runs(
        {registration.plugin_id for registration in registry.enabled()}
    )
    for registration in registry.enabled():
        assert registration.plugin is not None
        try:
            await registration.plugin.stop()
        except Exception:
            logger.exception(
                "collector plugin stop failed plugin_id=%s", registration.plugin_id
            )


def get_collector_registry() -> CollectorRegistry:
    if _registry is None:
        raise RuntimeError("collector registry is not initialized")
    return _registry


def _validate_plugin(plugin: CollectorPlugin, *, source: str) -> str | None:
    """manifest を検査し、最初の問題の文言を返す（問題なしなら ``None``）。

    判定の本体は plugin-api 側の ``check_manifest`` にある。プラグイン作者が手元で
    同じ関数を呼べるようにするためで、文言も一致させている。``builtin.*`` の予約だけは
    プラグインの出自（``source``）に依存するのでここに残る。
    """
    manifest = plugin.manifest
    if not _ID_RE.fullmatch(manifest.id):
        return "invalid plugin id"
    if source != "builtin" and manifest.id.startswith("builtin."):
        return "builtin.* is reserved"
    return manifest_error_message(manifest)


def _discover_external_collectors(settings: Settings):
    """外部プラグインをワーカープロセス経由で検出する。

    親プロセスでプラグインを import すると分離が崩れるため、``ep.load()`` は行わず、
    entry point 名の列挙（import を伴わない）だけで「検出すべきものがあるか」を判定し、
    あるときに限って短命のワーカーを起動する。

    Returns:
        ``(RemoteCollectorPlugin 一覧, entry point 名 → 失敗理由, 全体の失敗理由 or None)``。
    """
    from vcenter_event_assistant.plugins.remote import (
        build_remote_plugins,
        plugin_search_paths,
    )

    try:
        installed_names = [
            ep.name for ep in entry_points(group="vcenter_event_assistant.collectors")
        ]
    except Exception:
        logger.exception("collector entry point enumeration failed")
        installed_names = []
    if not installed_names and not plugin_search_paths(settings.plugin_dir):
        return [], {}, None

    try:
        plugins, failures = build_remote_plugins(settings.plugin_dir)
        return plugins, failures, None
    except Exception as exc:
        logger.exception("collector plugin discovery failed")
        return [], {}, f"plugin discovery failed: {type(exc).__name__}"


def build_collector_registry(
    settings: Settings,
    *,
    generation: int = 1,
    db_overrides: Mapping[str, Mapping[str, object]] | None = None,
) -> CollectorRegistry:
    """Discover, configure and validate collectors into one immutable snapshot.

    設定の優先順位は 環境変数 > ``db_overrides`` > TOML > manifest 既定値 である。
    ``db_overrides`` は呼び出し側が DB から読み出して渡す（本関数は I/O を行わない）。
    """
    from vcenter_event_assistant.plugins.builtin import builtin_collectors

    config_error: str | None = None
    try:
        configured = load_collector_config_file(settings.collector_config_file)
    except Exception as exc:
        configured = {}
        config_error = f"collector configuration load failed: {exc}"[:1000]
        logger.exception("collector configuration load failed")
    candidates: list[tuple[CollectorPlugin, str, str]] = [
        (p, "builtin", p.manifest.id) for p in builtin_collectors()
    ]
    load_failures: dict[str, CollectorRegistration] = {}
    remote_plugins, remote_failures, discovery_error = _discover_external_collectors(
        settings
    )
    for plugin in remote_plugins:
        candidates.append(
            (plugin, f"entry_point:{plugin.entry_point}", plugin.entry_point)
        )
    for name, reason in remote_failures.items():
        plugin_id = (
            f"invalid-entry-point:{name}" if name.startswith("builtin.") else name
        )
        load_failures[plugin_id] = CollectorRegistration(
            plugin_id, None, f"entry_point:{name}", None, "failed", reason
        )

    registrations: dict[str, CollectorRegistration] = dict(load_failures)
    if config_error:
        registrations["configuration"] = CollectorRegistration(
            "configuration", None, "configuration", None, "failed", config_error
        )
    if discovery_error:
        registrations["discovery"] = CollectorRegistration(
            "discovery", None, "discovery", None, "failed", discovery_error
        )
    metric_owners: dict[str, str] = {}
    for plugin, source, candidate_id in candidates:
        try:
            plugin_id = plugin.manifest.id
            error = (
                None
                if isinstance(plugin, CollectorPlugin)
                else "object does not implement CollectorPlugin"
            )
            error = error or _validate_plugin(plugin, source=source)
        except Exception as exc:
            registrations[candidate_id] = CollectorRegistration(
                candidate_id,
                None,
                source,
                None,
                "failed",
                f"invalid plugin contract: {type(exc).__name__}",
            )
            continue
        raw = apply_collector_environment(
            plugin_id,
            apply_collector_database_overrides(
                configured.get(plugin_id, {}),
                (db_overrides or {}).get(plugin_id),
            ),
        )
        default_enabled = source == "builtin"
        enabled = bool(raw.get("enabled", default_enabled))
        try:
            interval = int(
                raw.get(
                    "interval_seconds", _legacy_interval(settings, plugin_id, plugin)
                )
            )
            timeout = float(raw.get("timeout_seconds", 300.0))
            if interval < 10 or timeout <= 0:
                raise ValueError("invalid interval_seconds or timeout_seconds")
            values = raw.get("config", {})
            if not isinstance(values, dict):
                raise ValueError("config must be a TOML table")
            config = CollectorConfig(enabled, interval, timeout, values)
        except (TypeError, ValueError) as exc:
            config = None
            error = f"configuration error: {exc}"

        if plugin_id in registrations:
            error = "duplicate plugin id"
            previous = registrations[plugin_id]
            registrations[plugin_id] = CollectorRegistration(
                plugin_id,
                previous.plugin,
                previous.source,
                previous.config,
                "failed",
                error,
            )
            continue
        for definition in plugin.manifest.metric_definitions if enabled else ():
            owner = metric_owners.get(definition.key)
            if owner is not None:
                error = f"metric key {definition.key!r} is already owned by {owner}"
                break
            metric_owners[definition.key] = plugin_id
        status = "failed" if error else ("enabled" if enabled else "disabled")
        registrations[plugin_id] = CollectorRegistration(
            plugin_id, plugin, source, config, status, error
        )

    for plugin_id in configured.keys() - registrations.keys():
        registrations[plugin_id] = CollectorRegistration(
            plugin_id,
            None,
            "configuration",
            None,
            "failed",
            "configured plugin is not installed",
        )
    return CollectorRegistry(registrations, generation=generation)


def _legacy_interval(
    settings: Settings, plugin_id: str, plugin: CollectorPlugin
) -> int:
    if plugin_id == "builtin.vcenter.events":
        return settings.event_poll_interval_seconds
    if plugin_id.startswith("builtin.vcenter."):
        return settings.perf_sample_interval_seconds
    return plugin.manifest.default_interval_seconds
