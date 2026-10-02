"""An external collector: no imports from the VEA application."""

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectorManifest,
    LogRecordInput,
    SetupAction,
    SetupCheck,
    SetupResult,
)
from vcenter_event_assistant_plugin_api.logs import get_plugin_logger

from .config import PRESETS, sources_from_config
from .parser import STAMP, records
from .transport import LogFileChanged, ShellAccessError, open_reader, same_archived_file

MAX_READ_BYTES = 4 * 1024 * 1024
BOOTSTRAP_BYTES = 1024 * 1024
# Allow envelope overhead within the application's 8 MiB JSON Lines response.
MAX_BATCH_BYTES = 8 * 1024 * 1024 - 8192
logger = get_plugin_logger("vea.remote.logs")


def _encoded(record):
    value = asdict(record)
    for name in ("collected_at", "occurred_at"):
        if value[name] is not None:
            value[name] = value[name].isoformat()
    return value


def _size(logs, cursor):
    payload = {
        "events": [],
        "metrics": [],
        "logs": [_encoded(r) for r in logs],
        "next_cursor": json.dumps(cursor),
    }
    return len(json.dumps(payload).encode())


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _matches(state, file):
    n = state["prefix_length"]
    return (
        file.size >= state["offset"]
        and len(file.prefix) >= n
        and _hash(file.prefix[:n]) == state["prefix_hash"]
    )


class RemoteLogCollector:
    manifest = CollectorManifest(
        id="vea.remote.logs",
        display_name="VEA Remote Logs",
        version="0.2.0",
        data_kinds=frozenset({"log"}),
        default_interval_seconds=60,
        default_timeout_seconds=45,
        configuration_schema={
            "type": "object",
            "required": ["sources"],
            "additionalProperties": False,
            "properties": {
                "sources": {
                    "type": "array",
                    "title": "収集対象",
                    "minItems": 1,
                    "maxItems": 11,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "x-vea-ssh-connection": "ssh_connection_id",
                        "required": [
                            "id",
                            "vcenter_id",
                            "product",
                            "ssh_connection_id",
                        ],
                        "properties": {
                            "id": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 128,
                                "x-vea-generated-id": True,
                            },
                            "vcenter_id": {
                                "type": "string",
                                "minLength": 1,
                                "title": "vCenter",
                                "x-vea-widget": "vcenter",
                            },
                            "product": {
                                "type": "string",
                                "title": "製品",
                                "enum": ["esxi", "vcenter"],
                                "default": "esxi",
                            },
                            "inventory_host": {
                                "type": "string",
                                "title": "ESXiまたはvCenterのホスト名",
                                "x-vea-widget": "esxi-host",
                                "x-vea-vcenter-field": "vcenter_id",
                            },
                            "ssh_connection_id": {
                                "type": "string",
                                "minLength": 1,
                                "title": "SSH接続先",
                                "x-vea-widget": "ssh-connection",
                                "x-vea-host-field": "inventory_host",
                            },
                        },
                    },
                }
            },
        },
        setup_actions=(
            SetupAction("test_connection", "接続テスト", True),
            SetupAction("preview", "試し読み"),
        ),
        description="VEAが提供するログ収集プラグイン。ESXiのvmkernel・hostd・vpxaとvCenterのvpxdをSSHで差分収集する。",
    )

    async def start(self):
        pass

    async def stop(self):
        pass

    async def collect(self, context):
        if context.mock_mode:
            now = datetime.now(timezone.utc)
            return CollectionBatch(
                logs=(
                    LogRecordInput(
                        "mock-esxi",
                        "mock-esxi.local",
                        "vmkernel",
                        "mock-v1",
                        0,
                        now,
                        "Mock VMkernel log: no external connection",
                        now,
                        "info",
                    ),
                ),
                next_cursor=context.previous_cursor,
            )
        selected = [
            s
            for s in context.config.get("sources", [])
            if s.get("vcenter_id") == str(context.target.id)
        ]
        sources = sources_from_config({"sources": selected}) if selected else []
        if not sources:
            return CollectionBatch(next_cursor=context.previous_cursor)
        cursor = (
            json.loads(context.previous_cursor)
            if context.previous_cursor
            else {"version": 1, "streams": {}}
        )
        if cursor.get("version") != 1 or not isinstance(cursor.get("streams"), dict):
            raise ValueError("unsupported remote log cursor")
        # Each stream owns a disjoint share, so slow hosts cannot exhaust the budget.
        stream_count = sum(len(PRESETS[s.product]) for s in sources)
        wire_allowance = (MAX_BATCH_BYTES - 1024 * 1024) // stream_count
        allowance = MAX_READ_BYTES // stream_count
        semaphore = asyncio.Semaphore(2)
        now = datetime.now(timezone.utc)

        async def collect_source(source):
            async with semaphore:
                async with open_reader(source) as reader:
                    result = []
                    updates = {}
                    for kind in PRESETS[source.product]:
                        key = source.id + ":" + kind
                        previous = cursor["streams"].get(key)
                        read_budget = allowance
                        for attempt in range(3):
                            try:
                                logs, state = await self._stream(
                                    reader, source, kind, previous, read_budget, now,
                                    wire_allowance,
                                )
                                break
                            except LogFileChanged as exc:
                                read_budget -= exc.bytes_read
                                if attempt == 2 or read_budget <= 0:
                                    raise
                                logger.warning(
                                    "log changed during read; retrying source=%s kind=%s attempt=%d",
                                    source.id, kind, attempt + 1,
                                )
                        result.extend(logs)
                        updates[key] = state
                    return result, updates

        tasks = [asyncio.create_task(collect_source(s)) for s in sources]
        try:
            results = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        logs = []
        for rows, updates in results:
            logs.extend(rows)
            cursor["streams"].update(updates)
        if _size(logs, cursor) > MAX_BATCH_BYTES:
            # Defensive check; stream-local limits below leave room for metadata.
            raise ValueError("remote log batch exceeds encoded response limit")
        return CollectionBatch(logs=tuple(logs), next_cursor=json.dumps(cursor))

    async def setup(self, context, action):
        checks, samples, warnings = [], [], []
        selected = [
            s
            for s in context.config.get("sources", [])
            if s.get("vcenter_id") == str(context.target.id)
        ]
        for source in sources_from_config({"sources": selected}):
            stage_message = "SSH接続に失敗しました。SSHの有効化・ホスト名・ポートを確認してください。"
            try:
                async with open_reader(source) as reader:
                    checks.append(
                        SetupCheck(
                            source.id + ":auth",
                            source.host + " / SSH認証",
                            True,
                            "承認済みホスト鍵と鍵認証を確認しました。",
                        )
                    )
                    for command in ("stat", "tail", "head", "gzip"):
                        stage_message = f"{command}の実行確認に失敗しました。収集対象の製品種別・SSHシェル・コマンドの有無を管理者に確認してください。"
                        await reader.command(f"command -v {command}")
                    for kind, path in PRESETS[source.product].items():
                        import shlex

                        q = shlex.quote(path)
                        stage_message = f"{kind}を読み取れません。対象ログの存在とSSHユーザーの読取権限を確認してください。"
                        raw = await reader.command(f"test -r {q} && stat -L -c '%s' {q}")
                        size = int(raw.strip())
                        data = await reader.read(
                            path, max(0, size - 32768), min(size, 32768)
                        )
                        checks.append(
                            SetupCheck(
                                source.id + ":" + kind,
                                source.host + " / " + kind,
                                True,
                                "認証・読取・必要コマンドを確認しました。",
                            )
                        )
                        if action == "preview":
                            if size > len(data):
                                data = data.partition(b"\n")[2]
                            for begin, end, text, timestamp, severity in records(
                                data, 0, eof=True
                            ):
                                if len(samples) >= 20:
                                    break
                                samples.append(
                                    {
                                        "host": source.host,
                                        "log_kind": kind,
                                        "occurred_at": timestamp.isoformat()
                                        if timestamp
                                        else None,
                                        "message": text[:8192]
                                        + (
                                            "\n[試し読みの表示上限で省略]"
                                            if len(text) > 8192
                                            else ""
                                        ),
                                        "severity": severity,
                                    }
                                )
                            if not any(STAMP.match(line) for line in data.splitlines()):
                                warnings.append(
                                    source.host
                                    + " / "
                                    + kind
                                    + ": 時刻を解析できる行がありません。本文は保存できます。"
                                )
            except Exception as exc:
                name = type(exc).__name__
                message = (
                    "vCenterのBashシェルを実行できません。管理者にSSHユーザーのBashアクセスが有効か確認してください。既定シェルを変更する必要はありません。"
                    if isinstance(exc, ShellAccessError)
                    else
                    "ホスト鍵が一致しません。管理者に接続先の変更を確認してください。"
                    if "HostKey" in name
                    else "鍵認証に失敗しました。SSHユーザーと公開鍵の登録を確認してください。"
                    if "PermissionDenied" in name
                    else stage_message
                )
                checks.append(SetupCheck(source.id, source.host, False, message))
        return SetupResult(tuple(checks), tuple(warnings), tuple(samples))

    async def _stream(
        self, reader, source, kind, previous, allowance, now, wire_allowance
    ):
        files = await reader.files(kind, previous)
        states = previous["files"] if previous else []
        output = []
        encoded_size = 0
        wire_allowance = wire_allowance or MAX_BATCH_BYTES - 1024 * 1024
        remaining = allowance
        next_states = []
        # Retain only generations which still exist remotely. A compressed rename
        # is matched by the saved uncompressed prefix, not by its changed inode.
        matched = set()
        matches = {}
        for file in files:
            if file.metadata_only:
                for index, state in enumerate(states):
                    if index not in matched and same_archived_file(state, file):
                        matched.add(index)
                        matches[file.path] = state
                        break
                continue
            candidates = [
                i
                for i, state in enumerate(states)
                if i not in matched
                and not (state.get("metadata_only") and not state["prefix_length"])
                and _matches(state, file)
                and (not file.active or state["identity"] == file.identity)
            ]
            candidates.sort(key=lambda i: states[i]["identity"] != file.identity)
            candidate = None
            for index in candidates:
                old = states[index]
                n = old.get("checkpoint_length", 0)
                if (
                    not n
                    or _hash(await reader.read(file.path, old["offset"] - n, n))
                    == old["checkpoint_hash"]
                ):
                    candidate = index
                    break
            if candidate is not None:
                matched.add(candidate)
                matches[file.path] = states[candidate]
        missing = [
            s for i, s in enumerate(states) if i not in matched and not s.get("done")
        ]
        if missing:
            logger.warning(
                "remote log gap source=%s kind=%s: previous generation unavailable",
                source.id,
                kind,
            )
            warning = LogRecordInput(
                source.id,
                source.host,
                kind,
                "gap-" + uuid4().hex,
                0,
                now,
                "[collector] 読取位置を復元できません。ローテーションまたは切詰めによるログ欠落の可能性があります。",
                severity="warning",
            )
            output.append(warning)
            encoded_size += len(json.dumps(_encoded(warning)).encode()) + 2
        for file in files:
            state = matches.get(file.path)
            if previous is None and not file.active:
                # Bootstrap intentionally ignores historical rotations.
                state = self._state(file, file.size)
                state["done"] = True
            elif state is None:
                initial = max(0, file.size - BOOTSTRAP_BYTES) if previous is None else 0
                state = self._state(file, initial)
                if initial:
                    state["seek_record_start"] = True
                    # Check the preceding byte to avoid skipping a complete line.
                    preceding = await reader.read(file.path, initial - 1, 1)
                    state["skip_partial"] = preceding != b"\n"
            else:
                state = dict(state)
            state["identity"] = file.identity
            state["disk_size"] = file.disk_size
            state["modified"] = file.modified
            state["metadata_only"] = file.metadata_only
            if file.active:
                state["done"] = False
            if state.get("done") and not file.active:
                next_states.append(state)
                continue
            if remaining <= 0 or encoded_size >= wire_allowance:
                next_states.append(state)
                continue
            offset = state["offset"]
            wanted = min(remaining, max(0, file.size - offset))
            data = await reader.read(file.path, offset, wanted)
            remaining -= len(data)
            if len(data) != wanted:
                raise LogFileChanged("log changed during read", bytes_read=allowance - remaining)
            if state.get("skip_partial"):
                end = data.find(b"\n")
                if end < 0:
                    state["offset"] += len(data)
                    next_states.append(state)
                    continue
                offset += end + 1
                data = data[end + 1 :]
                state["offset"] = offset
                state.pop("skip_partial", None)
            if state.get("seek_record_start"):
                skipped = 0
                found_start = False
                for line in data.splitlines(keepends=True):
                    if STAMP.match(line):
                        found_start = True
                        break
                    if not line.endswith(b"\n"):
                        break
                    skipped += len(line)
                if skipped:
                    # Bootstrap may begin inside a multiline record. Its remaining
                    # continuation lines are context, not a complete new record.
                    offset += skipped
                    data = data[skipped:]
                    state["offset"] = offset
                if found_start:
                    state.pop("seek_record_start", None)
                else:
                    data = b""
            eof = not file.active and offset + len(data) >= file.size
            for begin, end, text, occurred_at, level in records(data, offset, eof=eof):
                record = LogRecordInput(
                    source.id,
                    source.host,
                    kind,
                    state["generation"],
                    begin,
                    now,
                    text,
                    occurred_at,
                    level,
                )
                # Encode actual escaped JSON, including non-ASCII expansion.
                # This per-stream cap sums to less than the wire limit.
                record_size = len(json.dumps(_encoded(record)).encode()) + 2
                if record_size > wire_allowance:
                    raise ValueError("log record exceeds encoded per-stream budget")
                if encoded_size + record_size > wire_allowance:
                    break
                output.append(record)
                encoded_size += record_size
                state["offset"] = end
            if (
                file.active
                and data
                and state["offset"] == offset
                and len(data) >= allowance
            ):
                raise ValueError("log record exceeds per-stream read budget")
            if eof and state["offset"] >= file.size:
                state["done"] = True
            # Detect a rotation/truncate during reading; retry the whole batch.
            # Reader metadata is checked on the next pass through a head checkpoint.
            if (
                file.prefix
                and await reader.read(file.path, 0, len(file.prefix)) != file.prefix
            ):
                raise LogFileChanged("log changed during read", bytes_read=allowance - remaining)
            n = min(state["offset"], 64)
            state["checkpoint_length"] = n
            state["checkpoint_hash"] = _hash(
                await reader.read(file.path, state["offset"] - n, n)
            )
            # Empty-file bootstrap gains a stable content fingerprint after append.
            if not state["prefix_length"] and file.prefix:
                state["prefix_length"] = len(file.prefix)
                state["prefix_hash"] = _hash(file.prefix)
            try:
                await reader.verify(file)
            except LogFileChanged as exc:
                exc.bytes_read = allowance - remaining
                raise
            next_states.append(state)
        return output, {"files": next_states}

    @staticmethod
    def _state(file, offset):
        return {
            "generation": uuid4().hex,
            "identity": file.identity,
            "offset": offset,
            "prefix_length": len(file.prefix),
            "prefix_hash": _hash(file.prefix),
            "done": False,
        }


build_collector = RemoteLogCollector
