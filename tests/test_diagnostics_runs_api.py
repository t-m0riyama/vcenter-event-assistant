"""診断 API の実行、監査、切断と保存の競合を検証する。"""

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import asyncssh
import pytest
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import Pool

from vcenter_event_assistant.api.routes import diagnostics as diagnostic_routes
from vcenter_event_assistant.api.schemas.diagnostics import DiagnosticPreviewInput
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.db.models import (
    DiagnosticCommand,
    DiagnosticTarget,
    Incident,
    IncidentDiagnosticRun,
    SSHConnection,
    SSHCredential,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.main import _rate_limit_spec, create_app
from vcenter_event_assistant.services.diagnostics import runs
from vcenter_event_assistant.services.diagnostics.ssh import DiagnosticResult, Output
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.settings_binding import bind_settings

pytestmark = pytest.mark.asyncio
AUDIT = "vcenter_event_assistant.audit"
COMMAND = "esxcli network nic stats get -n vmnic0"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("VEA_DIAGNOSTICS_ENABLED", "true")
    monkeypatch.setenv("VEA_SECRET_KEY", "diagnostics-test-key")
    monkeypatch.setenv("MOCK_MODE", "true")
    get_settings.cache_clear()
    return create_app()


@pytest.fixture
def audit_log(caplog):
    logger = logging.getLogger(AUDIT)
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


async def setup_run(client, *, custom=False):
    incident = (
        await client.post("/api/incidents", json={"title": "NIC", "status": "resolved"})
    ).json()["incident"]
    key = asyncssh.generate_private_key("ssh-ed25519")
    unique = uuid4().hex
    async with session_scope() as session:
        credential = SSHCredential(
            name="診断 SSH",
            purpose="diagnostics",
            private_key=key.export_private_key().decode(),
            public_key=key.export_public_key().decode(),
        )
        vc = VCenter(
            name=f"vCenter {unique}",
            host=f"vc-{unique}.example.net",
            username="reader",
            password="test",
        )
        session.add_all([credential, vc])
        await session.flush()
        connection = SSHConnection(
            name="ESXi SSH",
            purpose="diagnostics",
            host="esx.example.net",
            username="reader",
            approved_key=credential.public_key,
            credential_id=credential.id,
        )
        session.add(connection)
        await session.flush()
        now = utcnow()
        actor_fields = dict(
            created_at=now, updated_at=now, created_by="test", updated_by="test"
        )
        target = DiagnosticTarget(
            vcenter_id=vc.id,
            product="esxi",
            host_moid="host-5",
            host_name="ESXi 5",
            ssh_connection_id=connection.id,
            **actor_fields,
        )
        session.add(target)
        if custom:
            command = DiagnosticCommand(
                product="esxi",
                title="統計",
                description="",
                template="esxcli network nic stats get -n {{vmnic}}",
                param_definitions=[{"name": "vmnic", "type": "vmnic"}],
                **actor_fields,
            )
            session.add(command)
        await session.flush()
    path = f"/api/diagnostics/incidents/{incident['id']}/runs"
    payload = {
        "target_id": str(target.id),
        "params": {"vmnic": "vmnic0"},
        "command": {"custom": str(command.id)}
        if custom
        else {"builtin": "esxi.nic-stats"},
    }
    return SimpleNamespace(
        id=UUID(incident["id"]),
        target=target,
        connection=connection,
        detail=f"/api/incidents/{incident['id']}",
        path=path,
        payload=payload,
    )


async def preview(client, fixture):
    response = await client.post(fixture.path + "/preview", json=fixture.payload)
    assert response.status_code == 200, response.text
    return response.json()


async def request_payload(client, fixture):
    return {
        **fixture.payload,
        "fingerprint": (await preview(client, fixture))["fingerprint"],
    }


@pytest.mark.parametrize("incident_db", ["sqlite", "postgres"], indirect=True)
@pytest.mark.parametrize("custom", [False, True])
async def test_diagnostic_runs_cascade_postgres_and_sqlite(
    incident_db,
    app,
    open_client,
    custom,
    monkeypatch,
    audit_log,
):
    worker = Mock(side_effect=AssertionError("モックではワーカーを起動しない"))
    monkeypatch.setattr(runs, "CollectorWorker", worker)
    async with open_client(app=app) as client, open_client("viewer", app=app) as viewer:
        fixture = await setup_run(client, custom=custom)
        audit_log.clear()
        data = await preview(client, fixture)
        assert data == {
            "command_line": COMMAND,
            "host_name": "ESXi 5",
            "ssh_host": "esx.example.net",
            "ssh_port": 22,
            "ssh_username": "reader",
            "fingerprint": data["fingerprint"],
        }
        assert len(data["fingerprint"]) == 64
        assert data == await preview(client, fixture)
        assert "diagnostics.run." not in audit_log.text
        assert (
            await viewer.post(fixture.path + "/preview", json=fixture.payload)
        ).status_code == 403
        response = await client.post(
            fixture.path, json={**fixture.payload, "fingerprint": data["fingerprint"]}
        )
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["command_line"] == data["command_line"]
        assert (
            run["status"] == "succeeded"
            and run["exit_status"] == 0
            and run["executed"] is False
        )
        assert run["params"] == {"vmnic": "vmnic0"}

        monkeypatch.setenv("VEA_DIAGNOSTICS_ENABLED", "false")
        get_settings.cache_clear()
        assert (
            await client.post(fixture.path + "/preview", json=fixture.payload)
        ).status_code == 404
        detail = (await viewer.get(fixture.detail)).json()
        assert detail["status"] == "resolved"
        assert detail["diagnostic_runs"] == [run]
        assert "stdout" not in run and "stderr" not in run
        assert detail["entries"][-1]["kind"] == "diagnostic"
        assert "終了コード 0" in detail["entries"][-1]["body"]
        assert detail["updated_at"] == detail["entries"][-1]["created_at"]
        output_path = f"{fixture.detail}/diagnostic-runs/"
        output = (await viewer.get(f"{output_path}{run['id']}")).json()
        assert output["stderr"] == ""
        assert ("モックモード" if custom else "Packets received") in output["stdout"]
        assert (await viewer.get(f"{output_path}{2**65}")).status_code == 404
        assert (
            await viewer.get(f"/api/incidents/{uuid4()}/diagnostic-runs/{run['id']}")
        ).status_code == 404
        assert (await client.delete(fixture.detail)).status_code == 204
        assert (await viewer.get(f"{output_path}{run['id']}")).status_code == 404
    assert (
        "diagnostics.run.started" in audit_log.text
        and "diagnostics.run.finished" in audit_log.text
    )
    assert COMMAND in audit_log.text
    for secret in (
        "Packets received",
        "モックモードのため実行していません",
        "PRIVATE KEY",
        fixture.connection.approved_key,
    ):
        assert secret not in audit_log.text
    worker.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        "command",
        "target",
        "connection",
        "host_key",
        "product",
        "target_id",
        "ssh_host",
        "ssh_port",
    ],
)
async def test_diagnostics_rejects_drift_since_preview(
    app, open_client, audit_log, change, monkeypatch
):
    monkeypatch.setenv("VEA_SSH_ALLOWED_PORTS", "22,2222")
    get_settings.cache_clear()
    async with open_client(app=app) as client:
        fixture = await setup_run(client, custom=True)
        payload = await request_payload(client, fixture)
        async with session_scope() as session:
            if change == "command":
                await session.execute(
                    update(DiagnosticCommand).values(template="printf %s {{vmnic}}")
                )
            elif change == "target":
                await session.execute(update(DiagnosticTarget).values(host_name="別名"))
            elif change == "product":
                await session.execute(
                    update(DiagnosticTarget).values(product="vcenter", host_moid=None)
                )
                await session.execute(
                    update(DiagnosticCommand).values(product="vcenter")
                )
            elif change == "target_id":
                original = fixture.target
                replacement = DiagnosticTarget(
                    vcenter_id=original.vcenter_id,
                    product=original.product,
                    host_moid="host-6",
                    host_name=original.host_name,
                    ssh_connection_id=original.ssh_connection_id,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                    created_by="test",
                    updated_by="test",
                )
                session.add(replacement)
                await session.flush()
                payload["target_id"] = fixture.payload["target_id"] = str(
                    replacement.id
                )
            elif change == "ssh_host":
                await session.execute(
                    update(SSHConnection).values(host="other.example.net")
                )
            elif change == "ssh_port":
                await session.execute(update(SSHConnection).values(port=2222))
            elif change == "host_key":
                key = (
                    asyncssh.generate_private_key("ssh-ed25519")
                    .export_public_key()
                    .decode()
                )
                await session.execute(update(SSHConnection).values(approved_key=key))
            else:
                await session.execute(
                    update(SSHConnection).values(username="other-user")
                )
        response = await client.post(fixture.path, json=payload)
        assert response.status_code == 409
        assert response.headers["X-VEA-Error-Code"] == "diagnostic_changed"
        assert (await preview(client, fixture))["fingerprint"] != payload["fingerprint"]
        assert (
            "diagnostics.run.rejected" in audit_log.text
            and "diagnostic_changed" in audit_log.text
        )


async def test_diagnostics_params_product_host_key_and_rate_bucket(
    app, open_client, audit_log
):
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        assert _rate_limit_spec("POST", fixture.path) == ("diagnostics", 60)
        assert _rate_limit_spec("POST", fixture.path + "/preview") is None
        payload = {**fixture.payload, "params": {"unexpected": "value"}}
        preview_response = await client.post(fixture.path + "/preview", json=payload)
        assert preview_response.status_code == 422
        assert "diagnostics.run.rejected" not in audit_log.text
        response = await client.post(
            fixture.path, json={**payload, "fingerprint": "unused"}
        )
        assert response.headers["X-VEA-Error-Code"] == "diagnostic_params_invalid"
        assert (
            response.json()
            == preview_response.json()
            == {
                "detail": [
                    {"parameter": "unexpected", "reason": "unknown"},
                    {"parameter": "vmnic", "reason": "missing"},
                ]
            }
        )
        response = await client.post(
            fixture.path,
            json={
                **fixture.payload,
                "command": {"builtin": "vcenter.disk"},
                "fingerprint": "unused",
            },
        )
        assert response.headers["X-VEA-Error-Code"] == "diagnostic_product_mismatch"
        async with session_scope() as session:
            await session.execute(update(SSHConnection).values(approved_key=None))
        response = await client.post(
            fixture.path, json={**fixture.payload, "fingerprint": "unused"}
        )
        assert response.headers["X-VEA-Error-Code"] == "diagnostic_host_key_unapproved"


@pytest.mark.parametrize(
    "failure",
    ["startup", "harden", "dead_worker", "timeout", "malformed", "partial", "auth"],
)
async def test_diagnostics_worker_failures_and_hardening_order(
    app, open_client, audit_log, monkeypatch, failure
):
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(runs, "sys", SimpleNamespace(platform="linux"))
    harden_sent, ack = asyncio.Event(), asyncio.Event()
    kill = AsyncMock()

    async def request(payload, **kwargs):
        if payload["op"] == "harden":
            assert payload == {"op": "harden"}
            harden_sent.set()
            await ack.wait()
            if failure == "startup":
                raise runs.CollectorWorkerError("起動できません")
            return {"applied": failure != "harden"}
        assert payload["op"] == "diagnose" and kwargs["auto_start"] is False
        assert ack.is_set() and payload["ssh"]["private_key"].startswith("-----BEGIN")
        assert payload["command"] == {
            "builtin": "esxi.nic-stats",
            "params": {"vmnic": "vmnic0"},
        }
        assert payload["deadline_seconds"] == pytest.approx(kwargs["timeout"] - 2)
        if failure == "dead_worker":
            raise runs.CollectorWorkerError("停止")
        if failure == "timeout":
            raise TimeoutError
        if failure == "malformed":
            return {"garbage": "ssh output"}
        if failure == "auth":
            return DiagnosticResult(
                executed=False, error_code="auth_failed"
            ).model_dump()
        return DiagnosticResult(
            executed=True, error_code="timeout", stdout="part", stdout_bytes=4
        ).model_dump()

    ask = AsyncMock(side_effect=request)
    monkeypatch.setattr(
        runs,
        "CollectorWorker",
        lambda *_, **__: SimpleNamespace(request=ask, kill=kill),
    )
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        payload = await request_payload(client, fixture)
        http = asyncio.create_task(client.post(fixture.path, json=payload))
        await asyncio.wait_for(harden_sent.wait(), 5)
        assert ask.await_count == 1
        kill.assert_not_called()
        ack.set()
        response = await http
        assert response.status_code == 200, response.text
        row = response.json()
        assert row["status"] == "error" and row["command_line"] == COMMAND
        assert row["error_code"] == {
            "partial": "timeout",
            "auth": "auth_failed",
            "timeout": "timeout",
        }.get(failure, "worker_unavailable")
        assert row["executed"] is {"partial": True, "auth": False}.get(failure)
        if failure == "partial":
            output = await client.get(f"{fixture.detail}/diagnostic-runs/{row['id']}")
            assert output.json()["stdout"] == "part"
        assert ask.await_count == (1 if failure in {"harden", "startup"} else 2)
        kill.assert_awaited_once()
        assert COMMAND in audit_log.text
        assert "diagnostics.run.finished" in audit_log.text
        assert "PRIVATE KEY" not in audit_log.text


@pytest.mark.parametrize("scenario", ["limit_before", "limit_after", "gone"])
async def test_diagnostics_count_and_incident_rechecked_under_lock(
    app, open_client, audit_log, monkeypatch, scenario
):
    # 上限の前後を少ない行で作り、同じ照合を両方の段階で通す。
    assert runs.RUN_LIMIT == 100
    monkeypatch.setattr(runs, "RUN_LIMIT", 1)
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        payload = await request_payload(client, fixture)
        if scenario != "gone":
            if scenario == "limit_before":
                assert (
                    await client.post(fixture.path, json=payload)
                ).status_code == 200
            else:
                # 読み取りを通したあと、別の実行が最後の枠を使った状態を作る。
                async def execute(*_):
                    async with session_scope() as db:
                        db.add(
                            IncidentDiagnosticRun(
                                incident_id=fixture.id,
                                command_kind="builtin",
                                command_ref="esxi.hostname",
                                command_title="名前",
                                command_line="hostname",
                                params={},
                                product="esxi",
                                host_name="ESXi",
                                ssh_host="esx.example.net",
                                ssh_port=22,
                                ssh_username="reader",
                                status="succeeded",
                                stdout="",
                                stderr="",
                                stdout_truncated=False,
                                stderr_truncated=False,
                                elapsed_ms=0,
                                started_at=utcnow(),
                                finished_at=utcnow(),
                                run_by="test",
                            )
                        )
                    return DiagnosticResult(executed=True, exit_status=0)

                monkeypatch.setattr(runs, "_execute", execute)
        else:

            async def execute(*_):
                async with session_scope() as db:
                    await db.execute(delete(Incident).where(Incident.id == fixture.id))
                return DiagnosticResult(executed=True, exit_status=0)

            monkeypatch.setattr(runs, "_execute", execute)
        audit_log.clear()
        response = await client.post(fixture.path, json=payload)
        assert response.status_code == (404 if scenario == "gone" else 409)
        expected = (
            "incident_not_found" if scenario == "gone" else "incident_diagnostic_limit"
        )
        assert response.headers["X-VEA-Error-Code"] == expected
        assert expected in audit_log.text
        assert (
            f"diagnostics.run.{'rejected' if scenario == 'limit_before' else 'discarded'}"
            in audit_log.text
        )
        assert not app.state.diagnostic_runs.connections


@pytest.mark.parametrize("failure", ["timeout", "write", "commit"])
async def test_diagnostics_save_failure_rolls_back_and_releases_slot(
    app,
    open_client,
    audit_log,
    monkeypatch,
    failure,
):
    original_flush = AsyncSession.flush
    original_commit = AsyncSession.commit
    secret_error = "diagnostic-error-marker"
    secret_output = "diagnostic-output-marker"
    driver = RuntimeError(secret_error)
    driver.sqlstate = "40001"
    driver.pgcode = "23505"
    failure_error = OperationalError("書き込み", {"stdout": secret_output}, driver)
    monkeypatch.setattr(
        runs,
        "_execute",
        AsyncMock(
            return_value=DiagnosticResult(
                executed=True,
                exit_status=0,
                stdout=secret_output,
                stdout_bytes=len(secret_output),
            )
        ),
    )
    app_logger = logging.getLogger(runs.__name__)
    monkeypatch.setattr(
        app_logger, "handlers", [*app_logger.handlers, audit_log.handler]
    )

    async def fail_flush(session, *args, **kwargs):
        if any(isinstance(row, IncidentDiagnosticRun) for row in session.new):
            if failure == "timeout":
                await asyncio.Event().wait()
            if failure == "write":
                raise failure_error
            session.info["diagnostic_pending"] = True
        return await original_flush(session, *args, **kwargs)

    async def fail_commit(session):
        if session.info.get("diagnostic_pending"):
            raise failure_error
        return await original_commit(session)

    monkeypatch.setattr(AsyncSession, "flush", fail_flush)
    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    monkeypatch.setattr(runs, "SAVE_TIMEOUT", 0.05)
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        payload = await request_payload(client, fixture)
        before = (await client.get(fixture.detail)).json()
        response = await client.post(fixture.path, json=payload)
        assert response.status_code == 503
        assert response.headers["X-VEA-Error-Code"] == "diagnostic_save_failed"
        assert (await client.get(fixture.detail)).json() == before
        assert "diagnostics.run.discarded" in audit_log.text
        reason = "save_timeout" if failure == "timeout" else "save_failed"
        assert f"reason={reason}" in audit_log.text
        assert (
            "status=succeeded" in audit_log.text and "exit_status=0" in audit_log.text
        )
        assert "stdout_bytes=" in audit_log.text and "elapsed_ms=" in audit_log.text
        if failure != "timeout":
            log = next(
                record.getMessage()
                for record in audit_log.records
                if record.name == runs.__name__
            )
            assert (
                "OperationalError" in log and "RuntimeError" in log and "40001" in log
            )
        assert (
            secret_error not in audit_log.text and secret_output not in audit_log.text
        )
        assert not app.state.diagnostic_runs.connections


async def test_diagnostics_detached_run_releases_db_and_survives_request_cancellation(
    app,
    open_client,
    audit_log,
    monkeypatch,
):
    checked_out = set()
    ready, finish = asyncio.Event(), asyncio.Event()

    def checkout(_, record, __):
        checked_out.add(record)

    def checkin(_, record):
        checked_out.discard(record)

    async def execute(*_):
        assert not checked_out
        ready.set()
        await finish.wait()
        return DiagnosticResult(executed=True, exit_status=0)

    monkeypatch.setattr(runs, "_execute", execute)
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        payload = await request_payload(client, fixture)
        manager = app.state.diagnostic_runs
        event.listen(Pool, "checkout", checkout)
        event.listen(Pool, "checkin", checkin)
        http = asyncio.create_task(client.post(fixture.path, json=payload))
        try:
            await asyncio.wait_for(ready.wait(), 5)
            busy = await client.post(fixture.path, json=payload)
            assert busy.status_code == 409
            assert busy.headers["X-VEA-Error-Code"] == "diagnostic_busy"
            assert "diagnostics.run.rejected" in audit_log.text
            http.cancel()
            with pytest.raises(asyncio.CancelledError):
                await http
            (task,) = manager.tasks
            assert not task.cancelled()
            finish.set()
            await task
        finally:
            http.cancel()
            finish.set()
            event.remove(Pool, "checkout", checkout)
            event.remove(Pool, "checkin", checkin)
        detail = (await client.get(fixture.detail)).json()
        assert detail["diagnostic_runs"][0]["executed"] is True
        assert "diagnostics.run.finished" in audit_log.text
        assert not manager.tasks and not manager.connections


async def test_diagnostics_shutdown_cancels_pending_runs_and_kills_workers(
    app, open_client, audit_log, monkeypatch
):
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    bind_settings(get_settings())
    entered = asyncio.Event()
    kill = AsyncMock()

    async def request(body, **_):
        if body["op"] == "harden":
            return {"applied": True}
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        runs,
        "CollectorWorker",
        lambda *_, **__: SimpleNamespace(request=request, kill=kill),
    )
    monkeypatch.setattr(runs, "SHUTDOWN_TIMEOUT", 0)
    manager = app.state.diagnostic_runs
    try:
        async with app.router.lifespan_context(app):
            async with open_client(app=app) as client:
                fixture = await setup_run(client)
                payload = await request_payload(client, fixture)
                http = asyncio.create_task(client.post(fixture.path, json=payload))
                await asyncio.wait_for(entered.wait(), 5)
                http.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await http
        assert not manager.tasks and not manager.connections
        kill.assert_awaited_once()
        assert "diagnostics.run.aborted" in audit_log.text
        assert "diagnostics.run.finished" not in audit_log.text
        async with session_scope() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(IncidentDiagnosticRun)
                )
                == 0
            )
    finally:
        # lifespan の連携が壊れた場合もテスト後にタスクを残さない。
        if manager.tasks:
            await manager.shutdown()


async def test_diagnostics_global_slots_limit_distinct_connections(
    app, open_client, monkeypatch
):
    ready = asyncio.Queue()
    resume = asyncio.Event()

    async def execute(_settings, run):
        ready.put_nowait(run.connection_id)
        await resume.wait()
        return DiagnosticResult(executed=True, exit_status=0)

    monkeypatch.setattr(runs, "_execute", execute)
    async with open_client(app=app) as client:
        fixtures = [await setup_run(client) for _ in range(3)]
        payloads = [await request_payload(client, fixture) for fixture in fixtures]
        active = []
        try:
            for fixture, payload in zip(fixtures[:2], payloads[:2], strict=True):
                active.append(
                    asyncio.create_task(client.post(fixture.path, json=payload))
                )
                assert await asyncio.wait_for(ready.get(), 5) == fixture.connection.id
            response = await asyncio.wait_for(
                client.post(fixtures[2].path, json=payloads[2]), 2
            )
            assert response.status_code == 409
            assert response.headers["X-VEA-Error-Code"] == "diagnostic_busy"
        finally:
            resume.set()
            responses = await asyncio.gather(*active)
        assert all(item.status_code == 200 for item in responses)
        assert (
            await client.post(fixtures[2].path, json=payloads[2])
        ).status_code == 200


async def test_diagnostics_shutdown_after_commit_keeps_finished_audit(
    app, open_client, audit_log, monkeypatch
):
    original = runs.open_session
    committed = asyncio.Event()

    @asynccontextmanager
    async def delay_close(*args, **kwargs):
        async with original(*args, **kwargs) as session:
            yield session
        committed.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runs, "open_session", delay_close)
    monkeypatch.setattr(runs, "SHUTDOWN_TIMEOUT", 0)
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        payload = await request_payload(client, fixture)
        http = asyncio.create_task(client.post(fixture.path, json=payload))
        await asyncio.wait_for(committed.wait(), 5)
        http.cancel()
        with pytest.raises(asyncio.CancelledError):
            await http
        manager = app.state.diagnostic_runs
        await manager.shutdown()
        assert not manager.connections
        assert (
            "diagnostics.run.finished" in audit_log.text
            and "diagnostics.run.aborted" not in audit_log.text
        )
        detail = (await client.get(fixture.detail)).json()
        assert len(detail["diagnostic_runs"]) == 1


async def test_diagnostics_only_execution_counts_against_rate_limit(
    app, monkeypatch, open_client
):
    from vcenter_event_assistant.rate_limit import _rate_limiter

    monkeypatch.setenv("RATE_LIMIT_DIAGNOSTICS_PER_MINUTE", "1")
    monkeypatch.delenv("VEA_PYTEST")
    get_settings.cache_clear()
    app = create_app()
    _rate_limiter._hits.clear()
    try:
        async with open_client(app=app) as client:
            fixture = await setup_run(client)
            payload = await request_payload(client, fixture)
            assert (await client.post(fixture.path, json=payload)).status_code == 200
            assert (await client.post(fixture.path, json=payload)).status_code == 429
            assert (await preview(client, fixture))["fingerprint"] == payload[
                "fingerprint"
            ]
    finally:
        _rate_limiter._hits.clear()


@pytest.mark.parametrize(
    "invalid", ["port", "connection_purpose", "key_purpose", "key_changed_after_check"]
)
async def test_diagnostics_rejects_disallowed_ssh_settings(
    app, open_client, audit_log, monkeypatch, invalid
):
    monkeypatch.setenv("VEA_SSH_ALLOWED_PORTS", "22")
    get_settings.cache_clear()
    execute = AsyncMock()
    monkeypatch.setattr(runs, "_execute", execute)
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        payload = await request_payload(client, fixture)
        code = "diagnostic_connection_not_found"
        async with session_scope() as session:
            if invalid == "port":
                await session.execute(update(SSHConnection).values(port=2222))
                code = "diagnostic_port_not_allowed"
            elif invalid == "connection_purpose":
                await session.execute(update(SSHConnection).values(purpose="logs"))
            elif invalid == "key_purpose":
                await session.execute(update(SSHCredential).values(purpose="logs"))
        if invalid == "key_changed_after_check":
            # 接続先の取得後にも、秘密鍵を取り出す SQL が用途を照合する。
            original = runs.read_ssh_connection

            async def change_credential(session, identifier, purpose):
                connection = await original(session, identifier, purpose)
                assert connection is not None
                await session.execute(
                    update(SSHCredential)
                    .where(
                        SSHCredential.id == connection.credential_id,
                    )
                    .values(purpose="logs")
                )
                return connection

            monkeypatch.setattr(runs, "read_ssh_connection", change_credential)
            code = "diagnostic_credential_not_found"

        audit_log.clear()
        response = await client.post(fixture.path + "/preview", json=fixture.payload)
        assert response.status_code == (422 if invalid == "port" else 404)
        assert response.headers["X-VEA-Error-Code"] == code
        assert "diagnostics.run.rejected" not in audit_log.text
        executed = await client.post(fixture.path, json=payload)
        assert executed.status_code == response.status_code
        assert executed.headers["X-VEA-Error-Code"] == code
        assert (
            "diagnostics.run.rejected" in audit_log.text
            and f"reason={code}" in audit_log.text
        )
        execute.assert_not_awaited()


async def test_diagnostic_time_limits():
    assert runs.EXECUTION_TIMEOUT == 45
    assert runs.SAVE_TIMEOUT == 10
    assert runs.SHUTDOWN_TIMEOUT == 10


@pytest.mark.parametrize(
    "harden_finishes, kill_times_out",
    [(112, False), (112, True), (138, False), (139, False)],
)
async def test_diagnostic_worker_deadline_allocation(
    app, open_client, monkeypatch, harden_finishes, kill_times_out
):
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        settings = get_settings().model_copy(update={"mock_mode": False})
        prepared = await runs.prepare_run(
            settings, fixture.id, DiagnosticPreviewInput.model_validate(fixture.payload)
        )

    clock = Mock(return_value=100)
    limits = []

    @asynccontextmanager
    async def timeout_at(deadline):
        limits.append(deadline)
        yield
        if deadline == 145 and kill_times_out:
            raise TimeoutError

    async def request(payload, *, timeout, auto_start=True):
        if payload["op"] == "harden":
            assert timeout == 40 and auto_start
            clock.return_value = harden_finishes
            return {"applied": True}
        assert not auto_start
        assert payload["deadline_seconds"] == 26
        assert timeout == 28
        clock.return_value = 140
        return DiagnosticResult(executed=True, exit_status=0).model_dump()

    worker = SimpleNamespace(request=AsyncMock(side_effect=request), kill=AsyncMock())
    monkeypatch.setattr(runs, "CollectorWorker", lambda *_, **__: worker)
    monkeypatch.setattr(
        runs,
        "asyncio",
        SimpleNamespace(
            timeout_at=timeout_at,
            get_running_loop=lambda: SimpleNamespace(time=clock),
        ),
    )
    result = await runs._execute(settings, prepared)
    assert limits == [140, 145]
    worker.kill.assert_awaited_once()
    if harden_finishes >= 138:
        worker.request.assert_awaited_once()
        assert result.error_code == "timeout" and result.executed is None
    else:
        assert worker.request.await_count == 2
        assert result.exit_status == 0 and result.executed is True


@pytest.mark.parametrize("timeout_during", ["write", "cleanup"])
async def test_diagnostic_save_deadline_includes_failed_session_cleanup(
    app,
    open_client,
    audit_log,
    monkeypatch,
    timeout_during,
):
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    cleanup_done = asyncio.Event()
    original = runs.open_session

    @asynccontextmanager
    async def stalled_rollback(*args, **kwargs):
        async with original(*args, **kwargs) as session:
            try:
                yield session
            finally:
                cleanup_entered.set()
                try:
                    await cleanup_release.wait()
                except asyncio.CancelledError:
                    # 接続を返す DB ドライバの処理が取り消しを受けても残る場合を再現する。
                    await cleanup_release.wait()
                    raise
                finally:
                    cleanup_done.set()

    async def fail_save(*args, **kwargs):
        if timeout_during == "write":
            await asyncio.Event().wait()
        raise RuntimeError("保存失敗")

    monkeypatch.setattr(runs, "open_session", stalled_rollback)
    monkeypatch.setattr(runs, "_save_run", fail_save)
    monkeypatch.setattr(runs, "SAVE_TIMEOUT", 0.05)
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        payload = await request_payload(client, fixture)
        try:
            response = await asyncio.wait_for(
                client.post(fixture.path, json=payload), 2
            )
            assert response.status_code == 503
            await asyncio.wait_for(cleanup_entered.wait(), 2)
            assert not cleanup_done.is_set()
            assert "reason=save_timeout" in audit_log.text
            assert not app.state.diagnostic_runs.tasks
            assert not app.state.diagnostic_runs.connections
        finally:
            cleanup_release.set()
            if cleanup_entered.is_set():
                await asyncio.wait_for(cleanup_done.wait(), 2)


@pytest.mark.parametrize("stage", ["prepare", "execute", "save_cleanup"])
async def test_diagnostic_unexpected_error_is_audited_without_exception_message(
    app,
    open_client,
    audit_log,
    monkeypatch,
    stage,
):
    secret = "diagnostic-private-unexpected-message"
    with_log = logging.getLogger(
        diagnostic_routes.__name__ if stage == "prepare" else runs.__name__
    )
    monkeypatch.setattr(with_log, "handlers", [*with_log.handlers, audit_log.handler])
    error = RuntimeError(secret)
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        payload = await request_payload(client, fixture)
        if stage == "prepare":
            monkeypatch.setattr(
                diagnostic_routes, "prepare_run", AsyncMock(side_effect=error)
            )
        elif stage == "execute":
            monkeypatch.setattr(runs, "_execute", AsyncMock(side_effect=error))
        else:
            # 実行結果が組み立てられたあとの予期しない例外。
            monkeypatch.setattr(
                runs,
                "asyncio",
                SimpleNamespace(
                    create_task=asyncio.create_task,
                    get_running_loop=asyncio.get_running_loop,
                    timeout=Mock(side_effect=error),
                    CancelledError=asyncio.CancelledError,
                ),
            )
        response = await client.post(fixture.path, json=payload)
        assert response.status_code == 500 and secret not in response.text
        event = "rejected" if stage == "prepare" else "discarded"
        record = next(
            r.getMessage()
            for r in audit_log.records
            if f"diagnostics.run.{event}" in r.getMessage()
        )
        assert "reason=internal_error" in record
        if stage == "save_cleanup":
            assert "status=succeeded" in record and "exit_status=0" in record
        logged = [
            r
            for r in audit_log.records
            if r.name == with_log.name and "RuntimeError" in r.getMessage()
        ]
        assert logged and logged[0].levelno == logging.ERROR
        assert audit_log.records.index(logged[0]) > next(
            i for i, r in enumerate(audit_log.records) if r.getMessage() == record
        )
        assert secret not in audit_log.text
        assert not app.state.diagnostic_runs.connections


async def test_diagnostic_done_callback_logs_unhandled_task_error(
    app, open_client, audit_log, monkeypatch
):
    manager = app.state.diagnostic_runs
    logger = logging.getLogger(runs.__name__)
    monkeypatch.setattr(logger, "handlers", [*logger.handlers, audit_log.handler])
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        settings = get_settings()
        prepared = await runs.prepare_run(
            settings, fixture.id, DiagnosticPreviewInput.model_validate(fixture.payload)
        )
    monkeypatch.setattr(
        manager, "_run", AsyncMock(side_effect=RuntimeError("バックグラウンドの例外"))
    )
    manager.start(settings, prepared, runs.RunActor("tester", None, None, "tester"))
    await manager.shutdown()
    assert not manager.tasks
    assert "診断タスクが失敗しました" in audit_log.text
    assert "RuntimeError" in audit_log.text


@pytest.mark.parametrize("incident_db", ["sqlite", "postgres"], indirect=True)
async def test_diagnostic_nul_output_is_replaced_and_saved_on_postgres_and_sqlite(
    incident_db,
    app,
    open_client,
    monkeypatch,
):
    stdout, stderr = (
        Output(1024, bytearray(b"out\0put")),
        Output(1024, bytearray(b"err\0or")),
    )
    monkeypatch.setattr(
        runs,
        "_execute",
        AsyncMock(
            return_value=DiagnosticResult(
                executed=True,
                exit_status=0,
                stdout=stdout.text(),
                stderr=stderr.text(),
            )
        ),
    )
    async with open_client(app=app) as client:
        fixture = await setup_run(client)
        response = await client.post(
            fixture.path, json=await request_payload(client, fixture)
        )
        assert response.status_code == 200, response.text
        output = await client.get(
            f"{fixture.detail}/diagnostic-runs/{response.json()['id']}"
        )
        assert output.json()["stdout"] == "out\ufffdput"
        assert output.json()["stderr"] == "err\ufffdor"
