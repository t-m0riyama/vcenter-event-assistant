"""管理者向けの診断設定 API。"""

import asyncio
import logging
from typing import Annotated, TypeVar
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Delete, Update

from vcenter_event_assistant.api.auth_deps import (
    Principal,
    RequireAdmin,
    get_current_principal,
)
from vcenter_event_assistant.api.deps import get_app_settings, get_session
from vcenter_event_assistant.api.routes.incidents import IncidentId, incident_actor_name
from vcenter_event_assistant.api.diagnostics_audit import commit_audit
from vcenter_event_assistant.api.routes.setup_common import (
    DiagnosticsSetupRoute,
    list_hosts,
)
from vcenter_event_assistant.api.routes.ssh_setup import ssh_setup_router
from vcenter_event_assistant.api.schemas.diagnostics import (
    BuiltinCommandRead,
    CommandCatalog,
    CommandInput,
    CommandRead,
    CommandUpdate,
    DiagnosticPreview,
    DiagnosticPreviewInput,
    DiagnosticRunInput,
    DiagnosticRunRead,
    TargetInput,
    TargetRead,
    TargetUpdate,
)
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.db.models import (
    DiagnosticCommand,
    DiagnosticTarget,
    VCenter,
)
from vcenter_event_assistant.services.diagnostics.catalog import (
    BUILTIN_COMMANDS,
    PARAMETER_TYPES,
    TemplateError,
    validate_template,
)
from vcenter_event_assistant.services.diagnostics.runs import (
    DiagnosticRuns,
    RunActor,
    log_diagnostic_exception,
    prepare_run,
    rejection_reason,
    run_error,
)
from vcenter_event_assistant.services.ssh_management import read_ssh_connection
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/diagnostics",
    tags=["diagnostics"],
    dependencies=[RequireAdmin],
    route_class=DiagnosticsSetupRoute,
)
router.include_router(
    ssh_setup_router("diagnostics", route_class=DiagnosticsSetupRoute)
)
router.add_api_route("/vcenters/{identifier}/hosts", list_hosts, methods=["GET"])

Session = Annotated[AsyncSession, Depends(get_session)]
Actor = Annotated[Principal, Depends(get_current_principal)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
Setting = TypeVar("Setting", DiagnosticCommand, DiagnosticTarget)


async def _write_setting(
    session: AsyncSession,
    model: type[Setting],
    identifier: UUID,
    revision: UUID,
    *,
    statement: Update | Delete,
) -> Setting:
    # revision の照合と書き込みを一つの文にして、同時に届いた更新や削除を区別する。
    row = await session.scalar(
        statement.where(model.id == identifier, model.revision == revision).returning(
            model
        )
    )
    if row is not None:
        return row
    if await session.scalar(select(model.id).where(model.id == identifier)) is None:
        raise HTTPException(404, "診断設定が見つかりません。")
    raise HTTPException(
        409, "診断設定が変更されました。最新の設定を読み直してください。"
    )


async def _audit_command(
    session: Session, request: Request, actor: Actor, event: str, row: DiagnosticCommand
):
    await commit_audit(
        session,
        request,
        actor,
        f"command.{event}",
        command_id=row.id,
        title=row.title,
        product=row.product,
        template=row.template,
        param_definitions=row.param_definitions,
    )


async def _audit_target(
    session: Session, request: Request, actor: Actor, event: str, row: DiagnosticTarget
):
    await commit_audit(
        session,
        request,
        actor,
        f"target.{event}",
        target_id=row.id,
        vcenter_id=row.vcenter_id,
        product=row.product,
        host_moid=row.host_moid,
        host_name=row.host_name,
        ssh_connection_id=row.ssh_connection_id,
    )


def _validate_command(body: CommandInput) -> None:
    try:
        validate_template(
            body.template, [item.model_dump() for item in body.param_definitions]
        )
    except TemplateError as exc:
        raise HTTPException(
            422,
            {"reason": exc.reason, "parameter": exc.parameter},
            headers={"X-VEA-Error-Code": "diagnostic_template_invalid"},
        ) from None


async def _validate_target(session: AsyncSession, body: TargetInput) -> None:
    if (body.product == "vcenter") != (body.host_moid is None):
        raise HTTPException(
            422, "ESXi にはホストの moid を指定し、vCenter では空にしてください。"
        )
    if (
        await session.scalar(select(VCenter.id).where(VCenter.id == body.vcenter_id))
        is None
    ):
        raise HTTPException(422, "vCenter を選択してください。")
    if (
        await read_ssh_connection(session, body.ssh_connection_id, "diagnostics")
        is None
    ):
        raise HTTPException(422, "診断用の SSH 接続先を選択してください。")


@router.get("/commands")
async def list_commands(session: Session) -> CommandCatalog:
    rows = await session.scalars(
        select(DiagnosticCommand).order_by(
            DiagnosticCommand.title, DiagnosticCommand.id
        )
    )
    return CommandCatalog(
        builtin=[BuiltinCommandRead.model_validate(command, from_attributes=True)
                 for command in BUILTIN_COMMANDS.values()],
        custom=[CommandRead.model_validate(row) for row in rows],
        parameter_types=PARAMETER_TYPES,
    )


@router.post("/commands", status_code=201)
async def create_command(
    body: CommandInput, request: Request, session: Session, actor: Actor
) -> CommandRead:
    _validate_command(body)
    now = utcnow()
    row = DiagnosticCommand(
        **body.model_dump(),
        created_by=actor.username,
        updated_by=actor.username,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    result = CommandRead.model_validate(row)
    await _audit_command(session, request, actor, "created", row)
    return result


@router.put("/commands/{identifier}")
async def update_command(
    identifier: UUID,
    body: CommandUpdate,
    request: Request,
    session: Session,
    actor: Actor,
) -> CommandRead:
    _validate_command(body)
    row = await _write_setting(
        session,
        DiagnosticCommand,
        identifier,
        body.revision,
        statement=update(DiagnosticCommand).values(
            **body.model_dump(exclude={"revision"}),
            revision=uuid4(),
            updated_by=actor.username,
            updated_at=utcnow(),
        ),
    )
    result = CommandRead.model_validate(row)
    await _audit_command(session, request, actor, "updated", row)
    return result


@router.delete("/commands/{identifier}")
async def delete_command(
    identifier: UUID, revision: UUID, request: Request, session: Session, actor: Actor
):
    row = await _write_setting(
        session,
        DiagnosticCommand,
        identifier,
        revision,
        statement=delete(DiagnosticCommand),
    )
    await _audit_command(session, request, actor, "deleted", row)
    return {"ok": True}


@router.get("/targets")
async def list_targets(session: Session) -> list[TargetRead]:
    rows = await session.scalars(
        select(DiagnosticTarget).order_by(
            DiagnosticTarget.host_name, DiagnosticTarget.id
        )
    )
    return [TargetRead.model_validate(row) for row in rows]


@router.post("/targets", status_code=201)
async def create_target(
    body: TargetInput, request: Request, session: Session, actor: Actor
) -> TargetRead:
    await _validate_target(session, body)
    now = utcnow()
    row = DiagnosticTarget(
        **body.model_dump(),
        created_by=actor.username,
        updated_by=actor.username,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(
            409, "対象が登録済みか、接続設定が変更されました。"
        ) from None
    result = TargetRead.model_validate(row)
    await _audit_target(session, request, actor, "created", row)
    return result


@router.put("/targets/{identifier}")
async def update_target(
    identifier: UUID,
    body: TargetUpdate,
    request: Request,
    session: Session,
    actor: Actor,
) -> TargetRead:
    await _validate_target(session, body)
    try:
        row = await _write_setting(
            session,
            DiagnosticTarget,
            identifier,
            body.revision,
            statement=update(DiagnosticTarget).values(
                **body.model_dump(exclude={"revision"}),
                revision=uuid4(),
                updated_by=actor.username,
                updated_at=utcnow(),
            ),
        )
    except IntegrityError:
        raise HTTPException(
            409, "対象が登録済みか、接続設定が変更されました。"
        ) from None
    result = TargetRead.model_validate(row)
    await _audit_target(session, request, actor, "updated", row)
    return result


@router.delete("/targets/{identifier}")
async def delete_target(
    identifier: UUID, revision: UUID, request: Request, session: Session, actor: Actor
):
    row = await _write_setting(
        session,
        DiagnosticTarget,
        identifier,
        revision,
        statement=delete(DiagnosticTarget),
    )
    await _audit_target(session, request, actor, "deleted", row)
    return {"ok": True}


@router.post("/incidents/{id}/runs/preview")
async def preview_run(
    incident_id: IncidentId, body: DiagnosticPreviewInput, session: Session, settings: AppSettings,
) -> DiagnosticPreview:
    await session.commit()
    return (await prepare_run(settings, incident_id, body)).preview()


@router.post("/incidents/{id}/runs")
async def execute_run(
    incident_id: IncidentId, body: DiagnosticRunInput, request: Request, session: Session,
    settings: AppSettings, actor: Actor,
) -> DiagnosticRunRead:
    run_actor = RunActor(
        actor.username, actor.user_id, request.client.host if request.client else None, incident_actor_name(actor),
    )
    runs: DiagnosticRuns = request.app.state.diagnostic_runs
    fields = {"incident_id": incident_id, "target_id": body.target_id, **body.command.model_dump()}
    try:
        await session.commit()
        run = await prepare_run(settings, incident_id, body)
        if run.preview().fingerprint != body.fingerprint:
            raise run_error(409, "diagnostic_changed", "診断の設定が変わりました。プレビューを取り直してください。")
        task = runs.start(settings, run, run_actor)
    except HTTPException as exc:
        run_actor.audit("rejected", **fields, reason=rejection_reason(exc))
        raise
    except Exception as exc:
        run_actor.audit("rejected", **fields, reason="internal_error")
        log_diagnostic_exception(logger, "診断の準備中に予期しないエラーが発生しました。", exc)
        raise run_error(500, "diagnostic_internal_error", "診断を実行できませんでした。") from None
    return await asyncio.shield(task)
