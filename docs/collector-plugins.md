# Collector plugins

vCenter Event Assistant discovers collector plugins when the application starts. Built-in and
external collectors use the same versioned contract. External plugins are trusted Python code and
run with the same permissions as the application; install only packages you trust.

## Configuration

Set `VEA_COLLECTOR_CONFIG_FILE` to a TOML file. Built-in collectors are enabled by default. External
collectors are disabled unless their table sets `enabled = true`.

```toml
[collectors."builtin.vcenter.events"]
enabled = true
interval_seconds = 120
timeout_seconds = 300

[collectors."example.host.temperature"]
enabled = true
interval_seconds = 300
timeout_seconds = 60

[collectors."example.host.temperature".config]
sensor = "system-board"
```

Plugin-specific secrets should be read from environment variables owned and documented by that
plugin. Common settings and simple plugin values may override TOML with
`VEA_COLLECTOR__<NORMALIZED_PLUGIN_ID>__ENABLED`, `__INTERVAL_SECONDS`, `__TIMEOUT_SECONDS`, or
`__<CONFIG_KEY>`; dots and hyphens in the ID become underscores. For example,
`VEA_COLLECTOR__EXAMPLE_HOST_TEMPERATURE__SENSOR=cpu-package` overrides `config.sensor`.
Secrets must not be placed in the TOML file. Invalid, missing, or incompatible plugins appear
as `failed` in `GET /api/plugins/collectors`; they do not prevent the application from starting.

## Management screen

The read-only **Settings > Plugins** screen shows the effective common configuration and the latest
execution status for each vCenter. Change plugin configuration through TOML or environment variables,
then restart the application to rebuild the collector registry. The screen does not expose arbitrary
plugin configuration values or secrets.

## Package entry point

Plugins depend only on `vcenter-event-assistant-plugin-api` and publish a zero-argument factory:

```toml
[project.entry-points."vcenter_event_assistant.collectors"]
temperature = "example_temperature:build_collector"
```

The factory returns an object implementing `CollectorPlugin`. Metric keys must be declared in the
manifest and globally unique among installed collectors. The application validates each batch and
owns database writes, event scoring, duplicate handling, and cursor commits.

Installation and reload are intentionally startup-only in this release. Dynamic installation,
atomic registry replacement, rollback, and process isolation are reserved for the next phase.
