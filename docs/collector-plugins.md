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

The **Settings > Plugins** screen shows the effective common configuration and the latest execution
status for each vCenter. It never exposes arbitrary plugin configuration values or secrets.

The screen is read-only unless `VEA_PLUGIN_MANAGEMENT_ENABLED=true`. When management is enabled it
can also enable/disable collectors, change interval and timeout, install and uninstall packages, and
reload the registry without restarting the application.

**Installing, uninstalling, and reloading plugins is effectively arbitrary code execution.** This
application performs no authentication of its own, so enable management only when a reverse proxy
enforces authentication for `/api/plugins`. The setting is disabled by default.

## Package entry point

Plugins depend only on `vcenter-event-assistant-plugin-api` and publish a zero-argument factory:

```toml
[project.entry-points."vcenter_event_assistant.collectors"]
temperature = "example_temperature:build_collector"
```

The factory returns an object implementing `CollectorPlugin`. Metric keys must be declared in the
manifest and globally unique among installed collectors. The application validates each batch and
owns database writes, event scoring, duplicate handling, and cursor commits.

## Configuration precedence

Effective values are resolved in this order, highest first:

| Source | Scope | Notes |
|---|---|---|
| Environment variables | `enabled`, `interval_seconds`, `timeout_seconds`, plugin values | Always wins. Fields pinned here are reported as `env_locked_fields` and shown as read-only in the UI. |
| Database | `enabled`, `interval_seconds`, `timeout_seconds` | Written by the management screen. `NULL` means "unset" and defers to lower sources. |
| TOML file | everything | `VEA_COLLECTOR_CONFIG_FILE`. |
| Manifest defaults | `default_interval_seconds` | Declared by the plugin. |

Secrets belong in environment variables owned by the plugin; they are never stored in the database
or in the TOML file.

## Dynamic installation

Set `VEA_PLUGIN_DIR` (default `data/plugins`). Each distribution is installed in isolation with
`uv pip install --target` into `<VEA_PLUGIN_DIR>/<distribution>/<version>/`, so uninstalling and
rolling back are a directory removal. Install a package by uploading a `.whl` or `.tar.gz` from the
management screen; uploads run with `--no-index` and do not reach the network.

Installing by name from a package index requires `VEA_PLUGIN_ALLOW_INDEX_INSTALL=true` (and
optionally `VEA_PLUGIN_INDEX_URL`). It is disabled by default because of the supply-chain risk.
Requirements are restricted to `<name>` or `<name>==<version>`.

After installation the package is validated in an isolated worker: if it provides no
`vcenter_event_assistant.collectors` entry point, or the entry point fails to load, the install
directory is removed and nothing is registered. Newly installed collectors appear as `disabled`;
enable them and press **変更を反映** to apply.

In containers, mount `VEA_PLUGIN_DIR` on a persistent volume — otherwise installed plugins are lost
when the container is replaced. The `uv` binary must be present in the image (it already is).

## Hot reload

`POST /api/plugins/collectors/reload` (the **変更を反映** button) rebuilds the registry, activates
the new immutable snapshot atomically, reconciles the scheduler's collector jobs (adding, removing,
and rescheduling them), and only then drains and stops the previous generation. Restarting the
process is not required. The registry generation shown on the screen increments on every reload.

## Process isolation

External collectors run in a dedicated worker process per plugin, launched with the application's
own interpreter and with the plugin install directories appended to `sys.path` (so application
dependencies win over plugin-bundled ones). Built-in collectors continue to run in-process.

The application opens the vCenter connection on the worker side and passes the plugin only the
`open_vcenter_connection` factory, so the `CollectorPlugin` contract is unchanged. A plugin that
exceeds `timeout_seconds` has its worker killed, and a plugin that crashes its worker is reported as
`failed` without affecting the application or other plugins.

This isolates crashes, hangs, and dependency conflicts. It is **not** a sandbox against malicious
code: a plugin shares its worker process with the credentials passed to that worker. Install only
packages you trust.
