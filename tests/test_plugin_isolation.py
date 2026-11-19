from __future__ import annotations

import asyncio
import os
import stat
import sys
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from vcenter_event_assistant_plugin_api import CollectionBatch, CollectionContext, VCenterTarget

from vcenter_event_assistant.collectors.connection import build_ssl_context
from vcenter_event_assistant.db.models import InstalledPlugin
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.plugins import installer
from vcenter_event_assistant.plugins.install_client import _route, receive_artifact
from vcenter_event_assistant.plugins.publication import (
    clear_pending,
    migrate,
    publish,
    published_paths,
    read_catalog,
)
from vcenter_event_assistant.plugins.registry import (
    CollectorRegistration,
    CollectorRegistry,
    get_collector_registry,
    shutdown_collector_registry,
)
from vcenter_event_assistant.plugins.reload import reload_collector_registry
from vcenter_event_assistant.plugins.remote import (
    CollectorWorker,
    CollectorWorkerServiceError,
    RemoteCollectorPlugin,
    _discover_via_service,
    _request_context,
)
from vcenter_event_assistant.plugins.request_files import encode_file
from vcenter_event_assistant.plugins.service import WorkerSessionError, _run_worker, _spawn_worker
from vcenter_event_assistant.plugins.service_protocol import (
    ARTIFACT_LIMIT,
    WORKER_SESSION_READY,
    WORKER_SESSION_UNAVAILABLE,
    PluginServiceError,
    encode_header,
    role_uid,
)
from vcenter_event_assistant.plugins.subprocess_env import PROXY_ENV_VARS
from vcenter_event_assistant.plugins.wire import MAX_REQUEST_BYTES, ConnectionParams
from vcenter_event_assistant.plugins.worker import _handle
from vcenter_event_assistant.services import plugin_installs
from vcenter_event_assistant.services.plugin_installs import recover_plugin_publication
from vcenter_event_assistant.settings import Settings, get_settings


def test_migration_copies_manual_versions_and_can_resume(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    version = legacy / "manual" / "0.1.0"
    version.mkdir(parents=True)
    (version / "collector.py").write_text("# collector")
    (legacy / ".staging" / "unfinished").mkdir(parents=True)
    destination = tmp_path / "destination"
    destination.mkdir()
    # A failed migration can leave a copied generation before the catalog commit.
    partial = destination / ".generations" / "interrupted"
    partial.mkdir(parents=True)
    migrate(legacy, destination)
    paths = published_paths(destination)
    assert len(paths) == 1
    assert (Path(paths[0]) / "collector.py").read_text() == "# collector"
    assert not partial.exists()
    assert version.exists()
    migrate(legacy, destination)
    assert published_paths(destination) == paths


@pytest.mark.parametrize(
    "frames",
    [
        [{"file": "../outside", "size": 0, "executable": False}],
        [{"file": "/etc/invalid", "size": 0, "executable": False}],
        [{"link": "unsafe", "target": "target"}],
        [{"directory": "same"}, {"directory": "same"}],
        [{"file": "big", "size": ARTIFACT_LIMIT + 1, "executable": False}],
    ],
)
async def test_artifact_receiver_rejects_invalid_entries(tmp_path: Path, frames) -> None:
    reader = asyncio.StreamReader()
    for frame in frames:
        reader.feed_data(encode_header(frame))
    reader.feed_eof()
    with pytest.raises(PluginServiceError):
        await receive_artifact(reader, tmp_path)


async def test_artifact_receiver_preserves_regular_files(tmp_path: Path) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(encode_header({"directory": "example"}))
    reader.feed_data(encode_header({"file": "example/module.py", "size": 3, "executable": False}))
    reader.feed_data(b"# x")
    reader.feed_data(encode_header({"complete": True}))
    reader.feed_eof()
    await receive_artifact(reader, tmp_path)
    assert (tmp_path / "example" / "module.py").read_bytes() == b"# x"


def test_credentials_are_routed_only_to_installer(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (*PROXY_ENV_VARS, "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(variable, raising=False)
    settings = Settings(plugin_allow_index_install=True, plugin_index_url="https://u:p@example.test")
    monkeypatch.setenv("UV_OFFLINE", "true")
    monkeypatch.setenv("UV_INDEX_URL", "https://unrelated.example.test")
    role, request = _route(settings, "example", True)
    assert role == "installer"
    assert request["index"] == settings.plugin_index_url
    assert request["uv_options"]["UV_OFFLINE"] == "true"
    assert "UV_INDEX_URL" not in request["uv_options"]
    role, request = _route(settings, "example-0.1.0.tar.gz", False)
    assert role == "builder"
    assert request["index"] is None and request["proxies"] == {}
    settings.plugin_index_url = "https://mirror.example.test/simple"
    assert _route(settings, "example", True)[0] == "installer"
    settings.plugin_allow_unauthenticated_build_endpoints = True
    assert _route(settings, "example", True)[0] == "builder"


async def test_startup_recovers_publication_interrupted_before_db_commit(tmp_path: Path) -> None:
    settings = get_settings().model_copy(
        update={"plugin_dir": str(tmp_path / "plugins"), "plugin_service_socket_dir": "/sockets"}
    )
    root = Path(settings.plugin_dir)
    root.mkdir()
    migrate(tmp_path / "legacy", root)

    async with session_scope(settings=settings) as session:
        session.add(InstalledPlugin(distribution="example", status="installing", source="upload"))
    old_stage = root / "old"
    old_stage.mkdir()
    old_path = publish(root, old_stage, "example", "0.1.0", source="upload")
    clear_pending(root)
    staging = root / "staged"
    staging.mkdir()
    path = publish(root, staging, "example", "0.1.0", source="upload")
    assert old_path.is_dir()
    assert published_paths(root) == [str(path)]
    assert read_catalog(root)["pending"] is not None
    await recover_plugin_publication(settings)
    await recover_plugin_publication(settings)
    async with session_scope(settings=settings) as session:
        row = await session.scalar(select(InstalledPlugin).where(InstalledPlugin.distribution == "example"))
        assert row is not None
        assert row.status == "installed" and row.install_path == str(path)
    assert published_paths(root) == [str(path)]
    assert not old_path.exists()
    assert read_catalog(root)["pending"] is None


@pytest.mark.parametrize("operation", ["collect", "setup"])
async def test_worker_materializes_only_current_request_files(
    operation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VEA_PLUGIN_SERVICE_SOCKET_DIR", "/sockets")
    get_settings.cache_clear()
    ca = tmp_path / "app-ca.pem"
    private_key = ed25519.Ed25519PrivateKey.generate()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Plugin isolation test CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, algorithm=None)
    )
    ca.write_bytes(certificate.public_bytes(Encoding.PEM))
    expected_key = b"test-private-key"
    paths_seen = []

    @asynccontextmanager
    async def inspect_ca(params):
        path = Path(params.ca_bundle_path)
        assert path != ca
        ssl_context = build_ssl_context(verify_ssl=True, ca_bundle_path=str(path))
        assert certificate.public_bytes(Encoding.DER) in ssl_context.get_ca_certs(binary_form=True)
        paths_seen.append(path)
        yield None

    @dataclass
    class Setup:
        checks: tuple = ()

    class Plugin:
        manifest = SimpleNamespace(setup_actions=[SimpleNamespace(id="test")])

        async def check_files(self, context):
            path = Path(context.config["target"]["private_key_file"])
            assert path.read_bytes() == expected_key
            assert stat.S_IMODE(path.stat().st_mode) == 0o400
            paths_seen.append(path)
            async with context.open_vcenter_connection():
                pass

        async def collect(self, context):
            await self.check_files(context)
            return CollectionBatch()

        async def setup(self, context, action):
            await self.check_files(context)
            return Setup()

    monkeypatch.setattr("vcenter_event_assistant.plugins.worker._open_connection", inspect_ca)
    key = "/app-only/private-key"
    target = VCenterTarget(UUID(int=1), "test", "test.example", "https", 443, "test", True)
    context = CollectionContext(
        target, {"target": {"private_key_file": key}}, None, lambda: None,
    )
    params = ConnectionParams("test.example", "https", 443, "test", "test", True, ca_bundle_path=str(ca))
    payload = await _request_context(context, params, {key: encode_file(expected_key)})
    host = SimpleNamespace(load=lambda _: Plugin())
    await _handle(host, {**payload, "op": operation, "action": "test", "entry_point": "test"})
    assert len(paths_seen) == 2 and all(not path.exists() for path in paths_seen)
    assert ca.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux isolated worker supervision")
async def test_disconnected_client_stops_worker_with_blocked_stdin(tmp_path: Path) -> None:
    done = asyncio.Event()
    pid_path = tmp_path / "pid"
    program = """
import os
import subprocess
import sys
import time
from pathlib import Path

child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                         start_new_session=True)
Path(sys.argv[1]).write_text(f'{os.getpid()} {child.pid}')
time.sleep(60)
"""

    async def handle(reader, writer):
        try:
            await _run_worker([sys.executable, "-c", program, str(pid_path)], {}, reader, writer)
        finally:
            writer.close()
            done.set()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, limit=MAX_REQUEST_BYTES)
    async with server:
        _, writer = await asyncio.open_connection(*server.sockets[0].getsockname())
        try:
            async with asyncio.timeout(5):
                while not pid_path.exists() or not pid_path.stat().st_size:
                    await asyncio.sleep(0.01)
                writer.write(b"x" * (1024 * 1024) + b"\n")
                await writer.drain()
                await asyncio.sleep(0.05)
        finally:
            writer.transport.abort()
        await asyncio.wait_for(done.wait(), timeout=5)
    for pid in pid_path.read_text().split():
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid), 0)


async def test_shutdown_waits_for_dispatch_before_collectors_are_drained() -> None:
    registry = CollectorRegistry({})
    with registry.reserve():
        shutdown = asyncio.create_task(shutdown_collector_registry(registry))
        await asyncio.sleep(0)
        assert not shutdown.done()
    await asyncio.wait_for(shutdown, timeout=1)


@pytest.mark.parametrize("failure,listener_running", [
    ("disconnect", False), ("disconnect", True), ("timeout", True), ("oversize", True),
])
async def test_reload_distinguishes_plugin_start_failure_from_service_loss(
    failure: str, listener_running: bool, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = CollectorRegistry({})
    worker = CollectorWorker([], label="test")
    remote = RemoteCollectorPlugin(
        SimpleNamespace(id="test"), entry_point="test", worker=worker, start_timeout_seconds=0.02,
    )
    candidate = CollectorRegistry({
        "test": CollectorRegistration("test", remote, "external", None, "enabled")
    })

    async def disconnect():
        reader = asyncio.StreamReader(limit=64)
        if failure == "disconnect":
            reader.feed_eof()
        elif failure == "oversize":
            reader.feed_data(b"x" * 65 + b"\n")
        writer = SimpleNamespace(
            write=lambda _: None, drain=lambda: asyncio.sleep(0),
            transport=SimpleNamespace(abort=lambda: None),
        )
        worker._streams = reader, writer

    async def check_listener():
        if not listener_running:
            raise CollectorWorkerServiceError("listener unavailable")

    monkeypatch.setattr(worker, "ensure_started", disconnect)
    monkeypatch.setattr(
        "vcenter_event_assistant.plugins.remote._verify_worker_listener", check_listener
    )
    monkeypatch.setattr("vcenter_event_assistant.plugins.registry._registry", previous)
    monkeypatch.setattr(
        "vcenter_event_assistant.plugins.reload.build_collector_registry",
        lambda *args, **kwargs: candidate,
    )
    root = tmp_path / "plugins"
    root.mkdir()
    migrate(tmp_path / "legacy", root)
    settings = get_settings().model_copy(update={
        "plugin_service_socket_dir": "/sockets", "plugin_dir": str(root),
    })
    if not listener_running:
        with pytest.raises(CollectorWorkerServiceError):
            await reload_collector_registry(settings)
        assert get_collector_registry() is previous
    else:
        await reload_collector_registry(settings)
        assert get_collector_registry() is not previous
        assert get_collector_registry().get("test").status == "failed"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux child subreaper")
async def test_job_supervisor_reaps_descendants_outside_original_group(tmp_path: Path) -> None:
    from vcenter_event_assistant.plugins.service import _supervised

    pid_file = tmp_path / "child-pid"
    command = """
import subprocess
import sys
from pathlib import Path

child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                         start_new_session=True)
Path(sys.argv[1]).write_text(str(child.pid))
"""
    process = await asyncio.create_subprocess_exec(
        *_supervised(sys.executable, "-c", command, str(pid_file))
    )
    assert await asyncio.wait_for(process.wait(), 5) == 0
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


async def test_uninstall_returns_conflict_when_publication_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = asyncio.Lock()
    monkeypatch.setattr(plugin_installs, "_publication_lock", lock)
    settings = Settings(plugin_service_socket_dir="/sockets")
    async with lock, asyncio.timeout(1):
        with pytest.raises(plugin_installs.PluginPublicationBusyError):
            await plugin_installs.remove_installed_plugin(None, settings, "example")


async def test_worker_uses_role_local_ca_and_python_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vcenter_event_assistant.plugins import service

    monkeypatch.setenv("VEA_PLUGIN_DIR", str(tmp_path))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("SSL_CERT_FILE", "/worker/ca.pem")
    monkeypatch.setenv("PYTHONPATH", "/worker/python")
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)

    async def inspect(command, env, reader, writer):
        assert env["SSL_CERT_FILE"] == "/worker/ca.pem"
        assert env["PYTHONPATH"] == "/worker/python"
        assert "SSL_CERT_DIR" not in env

    monkeypatch.setattr(service, "_run_worker", inspect)
    await service._worker({
        "paths": [],
        "env": {
            "SSL_CERT_FILE": "/app/ca.pem", "SSL_CERT_DIR": "/app/certs",
            "PYTHONPATH": "/app/python",
        },
    }, None, None)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux isolated worker supervision")
async def test_worker_session_requires_supervisor_to_launch_child() -> None:
    with pytest.raises(WorkerSessionError):
        await _spawn_worker(["/no-such-worker-test-command"], {})


def test_discovery_skips_raw_output_until_matching_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = b'{"id":1,"ok":true,"result":{"plugins":[]}}'
    chunks = iter([
        encode_header(WORKER_SESSION_READY) + b"native out",
        b'put\n\xff\n{"ok":true}\n{"id":2,"ok":false}\n' + reply[:8],
        reply[8:] + b"\n",
    ])

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def recv(self, size):
            return next(chunks, b"")

        def settimeout(self, seconds):
            pass

        def connect(self, path):
            pass

        def sendall(self, data):
            pass

    monkeypatch.setattr("vcenter_event_assistant.plugins.remote.socket.socket", lambda *_: Socket())
    monkeypatch.setattr("vcenter_event_assistant.plugins.remote.verify_peer", lambda *_: None)
    assert _discover_via_service("/sockets", [], "{}\n") == reply.decode()


async def test_session_rejection_keeps_previous_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    migrate(tmp_path / "legacy", root)
    previous = CollectorRegistry({})
    worker = CollectorWorker([], label="test")
    plugin = RemoteCollectorPlugin(SimpleNamespace(id="test"), entry_point="test", worker=worker)
    candidate = CollectorRegistry({
        "test": CollectorRegistration("test", plugin, "external", None, "enabled"),
    })
    transport = SimpleNamespace(abort=lambda: None)

    async def rejected(*args, **kwargs):
        reader = asyncio.StreamReader()
        reader.feed_data(encode_header(WORKER_SESSION_UNAVAILABLE))
        return reader, SimpleNamespace(
            write=lambda _: None, drain=lambda: asyncio.sleep(0), transport=transport,
        )

    monkeypatch.setenv("VEA_PLUGIN_SERVICE_SOCKET_DIR", "/sockets")
    get_settings.cache_clear()
    settings = get_settings().model_copy(update={"plugin_dir": str(root)})
    monkeypatch.setattr("vcenter_event_assistant.plugins.remote.connect", rejected)
    monkeypatch.setattr("vcenter_event_assistant.plugins.registry._registry", previous)
    monkeypatch.setattr(
        "vcenter_event_assistant.plugins.reload.build_collector_registry",
        lambda *args, **kwargs: candidate,
    )
    with pytest.raises(CollectorWorkerServiceError):
        await reload_collector_registry(settings)
    assert get_collector_registry() is previous


def test_duplicate_isolated_roles_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEA_PLUGIN_INSTALLER_UID", "3456")
    monkeypatch.setenv("VEA_PLUGIN_BUILDER_UID", "3456")
    with pytest.raises(PluginServiceError, match="distinct non-root UID"):
        role_uid("worker")


async def test_queued_installs_recover_after_transient_database_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    migrate(tmp_path / "legacy", root)
    settings = get_settings().model_copy(
        update={"plugin_dir": str(root), "plugin_service_socket_dir": "/sockets"}
    )
    reconcile = plugin_installs._reconcile_publication
    failures = 0

    async def retry(settings):
        nonlocal failures
        if read_catalog(root)["pending"] and failures < 2:
            failures += 1
            raise OperationalError("test commit", {}, OSError("temporary failure"))
        await reconcile(settings)

    async def install(settings, *, source, from_index):
        staging = root / source
        staging.mkdir()
        publish(root, staging, source, "0.1.0", source="index")

    monkeypatch.setattr(plugin_installs, "_reconcile_publication", retry)
    monkeypatch.setattr(plugin_installs, "install_plugin", install)
    for distribution in ("first", "second"):
        async with session_scope(settings=settings) as session:
            await plugin_installs.start_install(
                session, settings, distribution=distribution, source=distribution,
                origin=distribution, from_index=True,
            )
    await asyncio.wait_for(plugin_installs.wait_for_installs(), timeout=5)
    async with session_scope(settings=settings) as session:
        rows = await plugin_installs.list_installed_plugins(session)
        assert {row.distribution: row.status for row in rows} == {
            "first": "installed", "second": "installed",
        }
    assert failures == 2 and read_catalog(root)["pending"] is None


async def test_cancelled_install_waits_for_publication_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    migrate(tmp_path / "legacy", root)
    settings = Settings(plugin_dir=str(root), plugin_service_socket_dir="/sockets")
    entered = threading.Event()
    release = threading.Event()

    async def install(settings, source, *, from_index, destination, timeout):
        (destination / "example-0.1.0.dist-info").mkdir()

    def delayed_publish(root, staging, distribution, version, *, source):
        entered.set()
        assert release.wait(timeout=5)
        assert staging.exists()
        return publish(root, staging, distribution, version, source=source)

    monkeypatch.setattr(installer, "install_via_service", install)
    monkeypatch.setattr(installer, "_validate_provides_collectors", lambda _: ("test.collector",))
    monkeypatch.setattr(installer, "publish", delayed_publish)
    task = asyncio.create_task(installer.install_plugin(
        settings, source="example-0.1.0-py3-none-any.whl", from_index=False,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(published_paths(root)) == 1
    assert read_catalog(root)["pending"]["version"] == "0.1.0"
