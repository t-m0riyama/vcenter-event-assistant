"""撮影用の診断データ。モックモードでだけ使う。"""

from datetime import datetime, timedelta

import asyncssh
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.schemas.incidents import TimedSource
from vcenter_event_assistant.auth.timeutil import as_utc
from vcenter_event_assistant.db.models import (
    DiagnosticTarget,
    EventRecord,
    Incident,
    IncidentDiagnosticRun,
    IncidentEntry,
    IncidentEvent,
    SSHConnection,
    SSHCredential,
    VCenter,
)
from vcenter_event_assistant.services.diagnostics.catalog import BUILTIN_COMMANDS, render_command
from vcenter_event_assistant.services.diagnostics.ssh import STDOUT_LIMIT
from vcenter_event_assistant.services.incidents import add_links, copy_event, record_link_additions
from vcenter_event_assistant.settings_binding import require_settings

_TITLE = "デモ: 診断コマンドで NIC を調査"
_ACTOR = "demo-diagnostics"
# 診断のホスト一覧がモックモードで返す識別子と名前にそろえる。
_HOST_MOID = "mock-esxi"
_HOST_NAME = "mock-esxi.local"

_CONNECTION_NAME = "デモ ESXi の診断用接続先"
_CREDENTIAL_NAME = "デモ診断用の鍵"
_EVENT_KEY = 9_004_001
_COLLECTOR = "builtin.vcenter.events"


async def _demo_connection(session: AsyncSession) -> SSHConnection:
    connection = await session.scalar(
        select(SSHConnection).join(SSHCredential).where(
            SSHConnection.purpose == "diagnostics", SSHConnection.name == _CONNECTION_NAME,
            SSHConnection.host == _HOST_NAME, SSHConnection.port == 22, SSHConnection.username == _ACTOR,
            SSHCredential.purpose == "diagnostics",
        ).order_by(SSHConnection.id)
    )
    if connection is not None:
        # 既存の接続先の承認状態は管理者の判断に従う。
        return connection

    credential_id = await session.scalar(
        select(SSHCredential.id).where(
            SSHCredential.purpose == "diagnostics", SSHCredential.name == _CREDENTIAL_NAME,
        ).order_by(SSHCredential.id)
    )
    if credential_id is None:
        identity = asyncssh.generate_private_key("ssh-ed25519")
        credential = SSHCredential(
            purpose="diagnostics", name=_CREDENTIAL_NAME,
            public_key=identity.export_public_key().decode(), private_key=identity.export_private_key().decode(),
        )
        session.add(credential)
        await session.flush()
        credential_id = credential.id

    host_key = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
    connection = SSHConnection(
        purpose="diagnostics", name=_CONNECTION_NAME, host=_HOST_NAME, port=22, username=_ACTOR,
        credential_id=credential_id, candidate_key=host_key, approved_key=host_key,
    )
    session.add(connection)
    await session.flush()
    return connection


async def seed_screenshot_diagnostics(session: AsyncSession, vcenter: VCenter, now: datetime) -> None:
    settings = require_settings()
    if not (settings.mock_mode and settings.diagnostics_enabled and settings.vea_secret_key):
        return

    target = await session.scalar(select(DiagnosticTarget).where(
        DiagnosticTarget.vcenter_id == vcenter.id, DiagnosticTarget.host_moid == _HOST_MOID,
    ))
    if target is None:
        connection = await _demo_connection(session)
        target = DiagnosticTarget(
            product="esxi", vcenter_id=vcenter.id, host_moid=_HOST_MOID, host_name=_HOST_NAME,
            ssh_connection_id=connection.id, created_at=now, updated_at=now, created_by=_ACTOR, updated_by=_ACTOR,
        )
        session.add(target)

    if await session.scalar(select(Incident.id).where(Incident.title == _TITLE, Incident.created_by == _ACTOR)) is not None:
        return

    event_time = now - timedelta(minutes=18)
    event = await session.scalar(select(EventRecord).where(
        EventRecord.vcenter_id == vcenter.id, EventRecord.collector_id == _COLLECTOR, EventRecord.vmware_key == _EVENT_KEY,
    ))
    if event is None:
        event = EventRecord(
            vcenter_id=vcenter.id, collector_id=_COLLECTOR, occurred_at=event_time, vmware_key=_EVENT_KEY,
            event_type="esx.problem.net.vmnic.linkstate.down",
            entity_type="HostSystem", entity_moid=_HOST_MOID, entity_name=_HOST_NAME,
            severity="warning", notable_score=40, message="（デモ）vmnic0 のリンクが切断されました。",
        )
        session.add(event)
    event_time = as_utc(event.occurred_at)
    incident = Incident(
        title=_TITLE, status="monitoring", level="warning", assignee=_ACTOR,
        summary="（デモ）物理 NIC のリンクが切断されました。対象のホスト名と NIC の統計を確認します。",
        started_at=event_time, created_at=event_time, updated_at=now, created_by=_ACTOR, updated_by=_ACTOR,
    )
    session.add(incident)
    await session.flush()

    links = await add_links(
        session, incident.id, IncidentEvent,
        [TimedSource(id=event.id, occurred_at=event_time)], copy_event, _ACTOR, event_time,
    )
    record_link_additions(session, incident.id, _ACTOR, event_time, (IncidentEvent, links))
    for minutes, command_id, params, exit_status, stdout, stderr in (
        (12, "esxi.hostname", {}, 0, f"Fully Qualified Domain Name: {_HOST_NAME}\nHost Name: mock-esxi\n", ""),
        (7, "esxi.nic-stats", {"vmnic": "vmnic0"}, 1,
         "（デモ）vmnic0 の統計\n" + "Packets received: 124508    Receive errors: 3\n" * 1600,
         "（デモ）NIC の統計の一部を取得できませんでした。\n"),
    ):
        command = BUILTIN_COMMANDS[command_id]
        started = now - timedelta(minutes=minutes)
        finished = started + timedelta(milliseconds=350)
        stdout_bytes = stdout.encode("utf-8")
        session.add_all([
            IncidentDiagnosticRun(
                incident_id=incident.id, command_kind="builtin", command_ref=command.id, command_title=command.title,
                command_line=render_command(command.template, command.param_definitions, params),
                # 手動登録された接続先を使う DB でも、保存する実行例の接続情報はデモ用にする。
                params=params, target_id=target.id, product="esxi", host_name=_HOST_NAME,
                ssh_host=_HOST_NAME, ssh_port=22, ssh_username=_ACTOR,
                executed=True, status="succeeded" if exit_status == 0 else "failed", exit_status=exit_status,
                stdout=stdout_bytes[:STDOUT_LIMIT].decode("utf-8", errors="replace"), stderr=stderr,
                stdout_truncated=len(stdout_bytes) > STDOUT_LIMIT, stderr_truncated=False,
                elapsed_ms=350, started_at=started, finished_at=finished, run_by=_ACTOR,
            ),
            IncidentEntry(
                incident_id=incident.id, kind="diagnostic", author=_ACTOR, created_at=finished,
                body=f"診断「{command.title}」を {_HOST_NAME} で実行した（終了コード {exit_status}）",
            ),
        ])
