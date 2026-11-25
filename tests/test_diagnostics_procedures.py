"""対応手順の同梱内容と、インシデントに紐付いた写しの照合を検証する。"""

from uuid import UUID, uuid4

import pytest

from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.db.models import (
    DiagnosticTarget,
    IncidentAlert,
    IncidentEvent,
    SSHConnection,
    SSHCredential,
    VCenter,
)
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.main import create_app
from vcenter_event_assistant.services.diagnostics.catalog import BUILTIN_COMMANDS
from vcenter_event_assistant.services.diagnostics.procedures import BUILTIN_PROCEDURES
from vcenter_event_assistant.services.event_patterns.definitions import BUILTIN_PATTERNS
from vcenter_event_assistant.settings import get_settings

PROCEDURES = "/api/event-patterns/procedures"
INCIDENTS = "/api/incidents"


def test_all_patterns_have_procedures_using_catalog_commands():
    assert set(BUILTIN_PROCEDURES) == {pattern.id for pattern in BUILTIN_PATTERNS}
    for steps in BUILTIN_PROCEDURES.values():
        # コマンドを使う最初の段で、接続先の取り違えを確かめる。
        first_with_commands = next(step for step in steps if step.command_ids)
        assert first_with_commands.command_ids == ("esxi.hostname",)
        for step in steps:
            assert step.text
            assert set(step.command_ids) <= BUILTIN_COMMANDS.keys()


def test_procedure_commands_match_the_plan_table():
    """計画書 5 章の表のコマンドの組み合わせを固定する。"""
    expected = {
        "host-conn-flapping": {"esxi.hostname", "esxi.hostd", "esxi.vpxa", "esxi.vmk", "esxi.ping", "esxi.uptime"},
        "host-reconnect-failed": {"esxi.hostname", "esxi.hostd", "esxi.vpxa", "esxi.vmk", "esxi.ping", "esxi.uptime"},
        "apd-timeout": {"esxi.hostname", "esxi.paths", "esxi.device", "esxi.adapters"},
        "apd-repeated": {"esxi.hostname", "esxi.paths", "esxi.device", "esxi.adapters"},
        "nic-link-flapping": {"esxi.hostname", "esxi.nic", "esxi.nic-stats"},
        "ha-failover": {"esxi.hostname", "esxi.fdm", "esxi.uptime", "esxi.maintenance"},
        "vmotion-failures": {"esxi.hostname", "esxi.vmk", "esxi.ping"},
    }
    assert {
        pattern_id: {command_id for step in steps for command_id in step.command_ids}
        for pattern_id, steps in BUILTIN_PROCEDURES.items()
    } == expected


@pytest.fixture
def disabled_app(monkeypatch):
    monkeypatch.setenv("VEA_DIAGNOSTICS_ENABLED", "false")
    get_settings.cache_clear()
    return create_app()


async def _create_incident(client):
    response = await client.post(INCIDENTS, json={"title": "調査中"})
    assert response.status_code == 201
    return UUID(response.json()["incident"]["id"])


@pytest.mark.asyncio
async def test_viewer_can_read_procedures_when_diagnostics_are_disabled(disabled_app, open_client):
    async with open_client(app=disabled_app) as admin:
        incident_id = await _create_incident(admin)
        assert (await admin.get("/api/diagnostics/targets")).status_code == 404

    path = f"{INCIDENTS}/{incident_id}/procedures"
    async with open_client("viewer", app=disabled_app) as viewer:
        response = await viewer.get(PROCEDURES)
        assert response.status_code == 200
        assert response.json() == [
            {
                "pattern_id": pattern.id,
                "title": pattern.title,
                "steps": [
                    {
                        "text": step.text,
                        "commands": [
                            {"id": command_id, "title": BUILTIN_COMMANDS[command_id].title}
                            for command_id in step.command_ids
                        ],
                    }
                    for step in BUILTIN_PROCEDURES[pattern.id]
                ],
            }
            for pattern in BUILTIN_PATTERNS
        ]
        empty = await viewer.get(path)
        assert empty.status_code == 200
        assert empty.json() == []
        for missing_id in ("invalid-uuid", str(uuid4())):
            response = await viewer.get(f"{INCIDENTS}/{missing_id}/procedures")
            assert response.status_code == 404
            assert response.json() == {"detail": "Incident not found"}

    async with open_client(None, app=disabled_app) as anonymous:
        assert (await anonymous.get(PROCEDURES)).status_code == 401
        assert (await anonymous.get(path)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("incident_db", ["sqlite", "postgres"], indirect=True)
async def test_diagnostic_candidates_from_copies_on_sqlite_and_postgres(incident_db, disabled_app, open_client):
    async with open_client(app=disabled_app) as admin:
        incident_id = await _create_incident(admin)
        other_incident_id = await _create_incident(admin)

    now = utcnow()
    async with session_scope() as session:
        vc = VCenter(name="vCenter", host="vc.test", username="test", password="test")
        other_vc = VCenter(name="別の vCenter", host="other-vc.test", username="test", password="test")
        credential = SSHCredential(name="診断用", purpose="diagnostics", private_key="非公開", public_key="公開鍵")
        session.add_all([vc, other_vc, credential])
        await session.flush()
        connection = SSHConnection(
            name="診断用", purpose="diagnostics", host="ssh-endpoint.test", username="ssh-account",
            credential_id=credential.id,
        )
        session.add(connection)
        await session.flush()

        def register_target(vcenter_id, moid, name):
            target = DiagnosticTarget(
                vcenter_id=vcenter_id, product="esxi", host_moid=moid, host_name=name,
                ssh_connection_id=connection.id, created_by="admin", updated_by="admin", created_at=now, updated_at=now,
            )
            session.add(target)
            return target

        host = register_target(vc.id, "host:42", "ESXi 42")
        register_target(other_vc.id, "host:42", "別の vCenter の ESXi 42")
        register_target(other_vc.id, "host-absent", "別の vCenter の ESXi")
        # 複数のホストが当たるときの確認用。どちらを先に選んでも対象が見つかるよう、両方を登録する。
        register_target(vc.id, "host:43", "ESXi 43")

        def alert(source_id, key, *, rule_type="event_pattern", incident=incident_id):
            row = IncidentAlert(
                incident_id=incident, alert_history_id=source_id, rule_id=1, rule_type=rule_type,
                alert_level="critical", state="firing", context_key=key, occurred_at=now,
                added_by="operator", added_at=now,
            )
            session.add(row)
            return row

        def event(source_id, event_type, entity_type, moid, *, incident=incident_id):
            return IncidentEvent(
                incident_id=incident, event_id=source_id, vcenter_id=vc.id, collector_id="test",
                vmware_key=source_id, vcenter_name=vc.name, occurred_at=now, event_type=event_type,
                notable_score=0, entity_type=entity_type, entity_moid=moid, message="イベント",
                added_by="operator", added_at=now,
            )

        # 写しの補助列がなくても、通知のキーからコロンを含む moid を取り出せる。
        apd = alert(1, f"{vc.id}:host:42:apd-timeout")
        reconnect = alert(2, f"{vc.id}:host:42:host-reconnect-failed")
        # 同じ moid で登録があっても、クラスタ対象の通知からは選ばない。
        ha = alert(3, f"{vc.id}:host:42:ha-failover")
        alert(4, f"{vc.id}::apd-repeated")
        alert(5, "invalid-uuid:host:42:apd-repeated")
        alert(6, f"{vc.id}:apd-repeated")
        alert(7, f"{vc.id}:host:42:unknown-pattern")
        alert(8, f"{vc.id}:host:42:apd-repeated", rule_type="event_score")
        alert(9, f"{vc.id}:host:42:apd-repeated", incident=other_incident_id)
        lost = event(1, "vim.event.HostConnectionLostEvent", "HostSystem", "host:42")
        nic = event(2, "esx.problem.net.vmnic.linkstate.down", "HostSystem", "host-absent")
        # HostSystem 以外のイベントは、登録済みの moid と一致しても先選択しない。
        migrated = event(3, "vim.event.VmFailedMigrateEvent", "VirtualMachine", "host:42")
        failed = event(4, "vim.event.DasHostFailedEvent", "ClusterComputeResource", "host:42")
        unrelated = event(5, "vim.event.VmPoweredOnEvent", "HostSystem", "host:42")
        other_lost = event(6, "vim.event.HostConnectionLostEvent", "HostSystem", "host:43")
        # 別のインシデントのイベントは候補に入れない。
        other_incident_event = event(
            7, "vim.event.HostConnectionLostEvent", "HostSystem", "host:43", incident=other_incident_id,
        )
        session.add_all([lost, nic, migrated, failed, unrelated, other_incident_event])
        await session.flush()

    async with open_client("viewer", app=disabled_app) as viewer:
        response = await viewer.get(f"{INCIDENTS}/{incident_id}/procedures")
        assert response.status_code == 200
        candidates = {item["procedure"]["pattern_id"]: item for item in response.json()}
        assert len(response.json()) == len(candidates) == 6
        expected_target = {"id": str(host.id), "host_name": "ESXi 42"}
        assert {
            pattern_id: ([(reason["kind"], reason["link_id"]) for reason in item["reasons"]], item["target"])
            for pattern_id, item in candidates.items()
        } == {
            "apd-timeout": ([("alert", apd.id)], expected_target),
            "host-reconnect-failed": ([("alert", reconnect.id), ("event", lost.id)], expected_target),
            "host-conn-flapping": ([("event", lost.id)], expected_target),
            "ha-failover": ([("alert", ha.id), ("event", failed.id)], None),
            "nic-link-flapping": ([("event", nic.id)], None),
            "vmotion-failures": ([("event", migrated.id)], None),
        }

        # 同じ手順に別のホストが該当したら、登録済みの対象が 1 台でも選ばない。
        async with session_scope() as session:
            session.add(other_lost)
        response = await viewer.get(f"{INCIDENTS}/{incident_id}/procedures")
        assert response.status_code == 200
        candidates = {item["procedure"]["pattern_id"]: item for item in response.json()}
        assert candidates["host-conn-flapping"]["target"] is None
        assert len(candidates["host-conn-flapping"]["reasons"]) == 2
        assert candidates["apd-timeout"]["target"] == expected_target
