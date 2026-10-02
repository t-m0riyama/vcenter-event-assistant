from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from vea_remote_log_collector import BOOTSTRAP_BYTES, RemoteLogCollector, _size
from vea_remote_log_collector.parser import records
from vea_remote_log_collector.transport import RemoteFile

NOW = datetime.now(timezone.utc)
SOURCE = SimpleNamespace(id="esxi-1", host="esxi.local", product="esxi")
A = b"2026-10-02T01:00:00Z error A\n"
B = b"2026-10-02T01:01:00Z info B\n"
C = b"2026-10-02T01:02:00Z warning C\n"


class Reader:
    def __init__(self, files=None):
        self.content = files or {"/var/run/log/vmkernel.log": ("inode-1", A + B)}
        self.reads = []

    async def verify(self, file):
        pass

    async def files(self, kind, previous=None):
        return [
            RemoteFile(path, identity, len(data), i, data[:256], path.endswith(".log"))
            for i, (path, (identity, data)) in enumerate(self.content.items())
        ]

    async def read(self, path, offset, length):
        self.reads.append((path, offset, length))
        return self.content[path][1][offset : offset + length]


async def stream(reader, state=None, allowance=1024 * 1024, wire=None):
    return await RemoteLogCollector()._stream(
        reader, SOURCE, "vmkernel", state, allowance, NOW, wire
    )


def test_parser_preserves_multiline_and_partial_bytes():
    raw = A + b" stack trace\n" + B + b" unfinished"
    parsed = list(records(raw, 100, eof=False))
    assert len(parsed) == 1
    assert parsed[0][0] == 100
    assert parsed[0][2].endswith(" stack trace")
    assert parsed[0][3] == datetime(2026, 10, 2, 1, tzinfo=timezone.utc)
    assert len(list(records(raw, 100, eof=True))) == 2
    assert not list(records(b"partial", 0, eof=False))
    assert list(records(b"unknown timestamp\n", 0, eof=False))[0][3] is None


async def test_append_restart_and_repeat_use_stable_generation():
    reader = Reader()
    rows, state = await stream(reader)
    assert [r.message for r in rows] == [A.decode().strip()]
    generation = rows[0].file_generation
    reader.content["/var/run/log/vmkernel.log"] = ("inode-1", A + B + C)
    rows, state = await stream(reader, json.loads(json.dumps(state)))
    assert [r.message for r in rows] == [B.decode().strip()]
    assert rows[0].file_generation == generation
    assert rows[0].byte_offset == len(A)
    rows, _ = await stream(reader, state)
    assert rows == []


async def test_rename_and_compressed_rotation_keep_generation():
    reader = Reader()
    rows, state = await stream(reader)
    generation = rows[0].file_generation
    reader.content = {
        "/var/run/log/vmkernel.1.gz": ("new-compressed-inode", A + B),
        "/var/run/log/vmkernel.log": ("inode-2", C + A),
    }
    rows, next_state = await stream(reader, state)
    assert [r.message for r in rows] == [B.decode().strip(), C.decode().strip()]
    assert rows[0].file_generation == generation
    assert next_state["files"][0]["done"]
    assert len({r.file_generation for r in rows}) == 2


async def test_truncate_or_missing_rotation_reports_gap_without_silent_skip():
    reader = Reader()
    _, state = await stream(reader)
    reader.content = {"/var/run/log/vmkernel.log": ("inode-1", C + A)}
    rows, next_state = await stream(reader, state)
    assert rows[0].message.startswith("[collector]")
    assert rows[0].severity == "warning"
    assert rows[1].message == C.decode().strip()
    assert next_state["files"][0]["offset"] == len(C)


async def test_bootstrap_starts_at_tail_and_skips_partial_first_line():
    data = b"x" * (BOOTSTRAP_BYTES + 20) + b"\n" + A + B
    reader = Reader(
        {
            "/var/run/log/vmkernel.log": ("i", data),
            "/var/run/log/vmkernel.1.gz": ("j", C),
        }
    )
    rows, state = await stream(reader)
    assert [r.message for r in rows] == [A.decode().strip()]
    assert state["files"][0]["offset"] == len(data) - len(B)
    assert state["files"][1]["done"]


async def test_metadata_only_bootstrap_archive_stays_skipped_after_restart():
    class MetadataReader(Reader):
        async def files(self, kind, previous=None):
            return [
                RemoteFile("/var/run/log/vmkernel.1.gz", "archive-inode", 0, 90, b"", False, 1024, True),
                RemoteFile("/var/run/log/vmkernel.log", "active-inode", len(A + B), 100, A + B, True, len(A + B)),
            ]

    reader = MetadataReader({"/var/run/log/vmkernel.log": ("active-inode", A + B)})
    rows, state = await stream(reader)
    assert [r.message for r in rows] == [A.decode().strip()]
    archive_generation = state["files"][0]["generation"]
    reader.reads.clear()
    rows, restored = await stream(reader, json.loads(json.dumps(state)))
    assert rows == []
    assert restored["files"][0]["generation"] == archive_generation
    assert all(not path.endswith(".gz") for path, _, _ in reader.reads)


async def test_completed_archive_retains_fingerprint_after_metadata_only_pass():
    from dataclasses import replace

    class CachedReader(Reader):
        metadata_only = False

        async def files(self, kind, previous=None):
            files = await super().files(kind, previous)
            return [replace(f, metadata_only=True, prefix=b"") if self.metadata_only and not f.active else f for f in files]

    reader = CachedReader()
    _, state = await stream(reader)
    reader.content = {
        "/var/run/log/vmkernel.1.gz": ("compressed-inode", A + B),
        "/var/run/log/vmkernel.log": ("active-2", C + A),
    }
    _, state = await stream(reader, state)
    generation = state["files"][0]["generation"]
    reader.metadata_only = True
    _, state = await stream(reader, state)
    reader.metadata_only = False
    reader.content["/var/run/log/vmkernel.1.gz"] = ("recompressed-inode", A + B)
    rows, state = await stream(reader, state)
    assert rows == []
    assert state["files"][0]["generation"] == generation


async def test_unterminated_line_is_retained_until_append():
    reader = Reader({"/var/run/log/vmkernel.log": ("i", b"unknown")})
    rows, state = await stream(reader)
    assert not rows
    reader.content["/var/run/log/vmkernel.log"] = ("i", b"unknown\n" + A + B)
    rows, _ = await stream(reader, state)
    assert rows[0].message == "unknown"
    assert rows[0].occurred_at is None


async def test_byte_budget_and_encoded_budget_do_not_advance_past_emitted_records():
    reader = Reader({"/var/run/log/vmkernel.log": ("i", A + B + C)})
    rows, state = await stream(reader, allowance=len(A + B))
    assert len(rows) == 1
    assert state["files"][0]["offset"] == len(A)
    rows2, state2 = await stream(reader, state, allowance=len(B + C))
    assert len(rows2) == 1
    assert state2["files"][0]["offset"] == len(A + B)
    assert (
        _size(rows, {"version": 1, "streams": {"esxi-1:vmkernel": state}})
        < 8 * 1024 * 1024
    )


async def test_mock_mode_never_opens_ssh(monkeypatch):
    async def fail(*args):
        raise AssertionError("external connection")

    monkeypatch.setattr("vea_remote_log_collector.open_reader", fail)
    batch = await RemoteLogCollector().collect(
        SimpleNamespace(mock_mode=True, previous_cursor=None)
    )
    assert batch.logs[0].log_kind == "vmkernel"


async def test_failure_cancels_sibling_connections_and_returns_no_batch(monkeypatch):
    import vea_remote_log_collector as module

    target_id = uuid4()
    sources = [
        SimpleNamespace(
            id="good", host="esxi-good", product="esxi", vcenter_id=target_id
        ),
        SimpleNamespace(
            id="bad", host="esxi-bad", product="esxi", vcenter_id=target_id
        ),
    ]
    monkeypatch.setattr(module, "sources_from_config", lambda _: sources)
    closed = []

    @asynccontextmanager
    async def open_fake(source):
        try:
            if source.id == "bad":
                raise ConnectionError("failed SSH")
            yield Reader()
        finally:
            closed.append(source.id)

    monkeypatch.setattr(module, "open_reader", open_fake)
    context = SimpleNamespace(
        mock_mode=False,
        config={"sources": [{"vcenter_id": str(target_id)}]},
        target=SimpleNamespace(id=target_id),
        previous_cursor=None,
    )
    with pytest.raises(ConnectionError):
        await RemoteLogCollector().collect(context)
    assert set(closed) == {"good", "bad"}


async def test_setup_explains_shell_failure_without_reporting_missing_stat(monkeypatch):
    import vea_remote_log_collector as module
    from vea_remote_log_collector.transport import ShellAccessError

    monkeypatch.setattr(module, "sources_from_config", lambda _: [SOURCE])

    class UnavailableShell:
        async def command(self, script):
            raise ShellAccessError("unavailable")

    @asynccontextmanager
    async def open_fake(source):
        yield UnavailableShell()

    monkeypatch.setattr(module, "open_reader", open_fake)
    result = await RemoteLogCollector().setup(
        SimpleNamespace(config={"sources": []}, target=SimpleNamespace(id=uuid4())),
        "test_connection",
    )
    assert not result.checks[-1].ok
    assert "Bashアクセス" in result.checks[-1].message
    assert "stat" not in result.checks[-1].message


@pytest.mark.parametrize("persistent", [False, True])
async def test_collect_retries_changed_snapshot_without_duplicating_records(monkeypatch, persistent):
    import vea_remote_log_collector as module
    from vea_remote_log_collector.transport import LogFileChanged

    target_id = uuid4()
    selected = SimpleNamespace(id="s", host="vc", product="vcenter", vcenter_id=target_id)
    monkeypatch.setattr(module, "sources_from_config", lambda _: [selected])

    class RotatingReader(Reader):
        verifies = 0

        async def verify(self, file):
            self.verifies += 1
            if persistent or self.verifies == 1:
                raise LogFileChanged("log rotated or truncated during read")

    reader = RotatingReader()

    @asynccontextmanager
    async def open_fake(source):
        yield reader

    monkeypatch.setattr(module, "open_reader", open_fake)
    context = SimpleNamespace(
        mock_mode=False, previous_cursor=None, target=SimpleNamespace(id=target_id),
        config={"sources": [{"vcenter_id": str(target_id)}]},
    )
    if persistent:
        with pytest.raises(LogFileChanged):
            await RemoteLogCollector().collect(context)
        assert reader.verifies == 3
    else:
        batch = await RemoteLogCollector().collect(context)
        assert reader.verifies == 2
        assert [r.message for r in batch.logs] == [A.decode().strip()]
        assert json.loads(batch.next_cursor)["streams"]["s:vpxd"]["files"][0]["offset"] == len(A)
    assert context.previous_cursor is None


async def test_snapshot_retry_stops_when_read_budget_is_exhausted(monkeypatch):
    import vea_remote_log_collector as module
    from vea_remote_log_collector.transport import LogFileChanged

    target_id = uuid4()
    selected = SimpleNamespace(id="s", host="vc", product="vcenter", vcenter_id=target_id)
    monkeypatch.setattr(module, "sources_from_config", lambda _: [selected])
    monkeypatch.setattr(module, "MAX_READ_BYTES", len(A + B))

    class RotatingReader(Reader):
        verifies = 0

        async def verify(self, file):
            self.verifies += 1
            raise LogFileChanged("log rotated or truncated during read")

    reader = RotatingReader()

    @asynccontextmanager
    async def open_fake(source):
        yield reader

    monkeypatch.setattr(module, "open_reader", open_fake)
    context = SimpleNamespace(
        mock_mode=False, previous_cursor=None, target=SimpleNamespace(id=target_id),
        config={"sources": [{"vcenter_id": str(target_id)}]},
    )
    with pytest.raises(LogFileChanged):
        await RemoteLogCollector().collect(context)
    assert reader.verifies == 1


async def test_bootstrap_skips_continuations_until_a_complete_record(monkeypatch):
    import vea_remote_log_collector as module

    monkeypatch.setattr(module, "BOOTSTRAP_BYTES", len(A + B) + 8)
    reader = Reader(
        {"/var/run/log/vmkernel.log": ("i", b"ignored start\n stack context\n" + A + B)}
    )
    rows, _ = await stream(reader)
    assert [r.message for r in rows] == [A.decode().strip()]
