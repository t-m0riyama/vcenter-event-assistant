# VEA Remote Logs collector

VEA-provided, bundled collector `vea.remote.logs` for vCenter Event Assistant.
The collector runs in an independent worker and collects ESXi and vCenter logs.
Requires plugin-api **1.4 or later**, Python 3.12+, and AsyncSSH 2.24+.
The application must include the remote-log storage migration and search API.

Reads ESXi 8 `vmkernel`, `hostd`, `vpxa`, and vCenter 8 `vpxd` through SSH.
Uses explicit key authentication and known_hosts verification, fixed read-only shell
commands, and no vCenter API session, remote agent installation, SFTP dependency,
or changes to the server's default shell.

For the standard application, this independent package and AsyncSSH are now
included by `uv sync` and the Docker build. Collection remains disabled until
configured. Use **Settings → Plugins → Start setup** to select vCenters and hosts,
generate or upload an SSH key, approve the host fingerprint, test, and enable.
The application manages encrypted keys and known_hosts; no manual mounts are required.
See the [Japanese walkthrough](../../docs/remote-log-collector.md).

## Build and install separately

For plugin developers or custom application distributions:

```sh
uv build --package vcenter-event-assistant-plugin-api
uv build --package vea-remote-log-collector
uv pip install --python /path/to/application/python \
  dist/vcenter_event_assistant_plugin_api-1.4.0-py3-none-any.whl \
  dist/vea_remote_log_collector-0.2.0-py3-none-any.whl
```

UI wheel upload continues to use `--no-deps`. For third-party/custom distributions,
install required dependencies into the application's interpreter first. Offline
installations need platform-appropriate wheels for AsyncSSH and its dependencies:
`uv pip install --no-index --find-links /wheelhouse ...`.

## Configuration

Set `VEA_COLLECTOR_CONFIG_FILE=/config/collectors.toml` and mount the key and
known_hosts files read-only. Validate host fingerprints through your normal
trusted channel before populating known_hosts. Do not disable host verification.
SSH must already be enabled, and the SSH account must be able to read the logs.
Encrypted keys requiring an interactive passphrase are not supported in v1.

```toml
[collectors."vea.remote.logs"]
enabled = false
interval_seconds = 60
timeout_seconds = 45

[[collectors."vea.remote.logs".config.sources]]
id = "esxi-01"
vcenter_id = "00000000-0000-0000-0000-000000000001" # registered vCenter UUID
product = "esxi"
host = "esxi-01.example.net"
port = 22
username = "log-reader"
private_key_file = "/run/secrets/esxi-log-key"
known_hosts_file = "/config/known_hosts"

[[collectors."vea.remote.logs".config.sources]]
id = "vcenter-01"
vcenter_id = "00000000-0000-0000-0000-000000000001"
product = "vcenter"
host = "vcenter-01.example.net"
username = "log-reader"
private_key_file = "/run/secrets/vcenter-log-key"
known_hosts_file = "/config/known_hosts"
```

A source ID is permanent: changing it starts a fresh cursor. Assign each source to
one registered vCenter, and keep that vCenter enabled. There is no automatic ESXi
discovery. Only the four preset log kinds are supported.

## Collection and limits

- ESXi preset path: `/var/run/log/{vmkernel,hostd,vpxa}.log`.
- vCenter preset path: `/var/log/vmware/vpxd/vpxd.log`.
- ESXi numeric rotations (`name.N`, `name.log.N`) and vCenter
  `vpxd-N.log`, optionally gzip compressed, are followed oldest first.
- First enable reads the last 1 MiB of each **current** file, dropping a partial
  initial record and its continuation lines. Historical rotations are skipped. Following runs read differences.
- At most 4 MiB of log data per vCenter per run, shared fairly across streams,
  with at most two concurrent SSH connections. Metadata and consistency probes
  add small transfers. At most 64 files per stream are inspected.
- Byte positions refer to uncompressed data. Prefix and checkpoint hashes track
  rename/compression and detect truncate. If an unfinished generation disappears,
  a `[collector]` warning record identifies possible missing logs.
- Multiline timestamped records are confirmed when the next timestamp arrives;
  the final active record and partial line remain for the next run. This preserves
  stack traces split across polling boundaries. Rotated files flush their last
  record at EOF. Untimed standalone lines retain a null occurrence timestamp.
- A record exceeding its stream's read or encoded budget fails the run explicitly;
  text is never silently shortened. JSON escaping is counted against the 8 MiB
  worker response limit. Successful cursor positions cover only emitted records.
- Any SSH/read failure rejects the whole vCenter batch and preserves the prior
  DB cursor. Other vCenters continue. Retry is idempotent by source/kind/generation/
  byte offset. Network timeouts close connections; the worker timeout remains
  an outer bound.
- Gzip rotations require remote decompression for size and range reads; large
  compressed backlogs can require increasing the timeout. This is designed for
  at most ten ESXi hosts, not an enterprise log-storage replacement.

## Tests and rollout

From the repository root, with its development environment:

```sh
uv run pytest packages/remote-log-collector/tests tests/test_remote_logs.py -q
```

Before production enablement, validate on **your ESXi/vCenter 8 builds**: SSH keys
and host fingerprints, read permissions, BusyBox `stat/tail/head/gzip`, vCenter
` shell /bin/bash -c ...` execution through appliance shell, timestamp formats,
rotations, reconnects, and collection duration. Automated tests do not certify a
particular appliance build. Server-side SSH settings are not changed by this plugin.

Enable one source first, inspect plugin execution state and log search, then add
sources. Default retention is `LOG_RETENTION_DAYS=7`; old logs are deleted by the
existing retention job (`PURGE_INTERVAL_HOURS`, default six hours).
