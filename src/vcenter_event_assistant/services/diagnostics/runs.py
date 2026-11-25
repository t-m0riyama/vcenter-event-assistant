"""診断のプレビュー、実行枠、ワーカーとの通信、結果の保存。"""

import asyncio
import hashlib
import json
import logging
import re
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.schemas.diagnostics import (
    BuiltinCommandRef,
    DiagnosticPreview,
    DiagnosticPreviewInput,
    DiagnosticRunRead,
    Product,
)
from vcenter_event_assistant.auth.audit import audit
from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.db.models import (
    DiagnosticCommand,
    DiagnosticTarget,
    Incident,
    IncidentDiagnosticRun,
    IncidentEntry,
    SSHCredential,
)
from vcenter_event_assistant.db.session import open_session, session_scope
from vcenter_event_assistant.plugins.remote import CollectorWorker, CollectorWorkerError
from vcenter_event_assistant.services.diagnostics.catalog import (
    BUILTIN_COMMANDS,
    ParameterError,
    TemplateError,
    normalize_parameter,
    render_command,
)
from vcenter_event_assistant.services.diagnostics.ssh import (
    CustomCommand,
    DiagnosticResult,
    SSHDestination,
    WorkerCommand,
)
from vcenter_event_assistant.services.incidents import (
    lock_incident,
    mark_incident_updated,
)
from vcenter_event_assistant.services.ssh_management import (
    check_ssh_port,
    read_ssh_connection,
)
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

RUN_LIMIT = 100
EXECUTION_TIMEOUT = 45
SAVE_TIMEOUT = 10
SHUTDOWN_TIMEOUT = 10


def run_error(status: int, code: str, detail: object) -> HTTPException:
    return HTTPException(status, detail, headers={"X-VEA-Error-Code": code})


def log_diagnostic_exception(log: logging.Logger, message: str, exc: Exception) -> None:
    # 例外の文言には接続情報や出力が含まれることがある。
    log.error(
        "%s (%s)\n%s",
        message,
        type(exc).__name__,
        "\n".join(
            f"{frame.f_code.co_filename}:{lineno} ({frame.f_code.co_name})"
            for frame, lineno in traceback.walk_tb(exc.__traceback__)
        ),
    )


def _log_save_failure(reason: str, exc: Exception) -> None:
    # DB ドライバの例外には SQL の引数（診断の出力）が含まれることがある。
    original = getattr(exc, "orig", None)
    state = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    sqlstate = (
        state
        if isinstance(state, str) and re.fullmatch(r"[0-9A-Z]{5}", state)
        else None
    )
    logger.warning(
        "診断結果の保存処理に失敗しました: reason=%s exception=%s orig=%s sqlstate=%s",
        reason,
        type(exc).__name__,
        type(original).__name__ if original is not None else None,
        sqlstate,
    )


async def _check_run_limit(session: AsyncSession, incident_id: UUID) -> None:
    count = await session.scalar(
        select(func.count())
        .select_from(IncidentDiagnosticRun)
        .where(IncidentDiagnosticRun.incident_id == incident_id)
    )
    if count is not None and count >= RUN_LIMIT:
        raise run_error(
            409, "incident_diagnostic_limit", "診断の結果は 100 件まで保存できます。"
        )


@dataclass(frozen=True)
class PreparedRun:
    incident_id: UUID
    target_id: UUID
    connection_id: UUID
    product: Product
    kind: Literal["builtin", "custom"]
    ref: str
    title: str
    host_name: str
    line: str
    command: WorkerCommand
    ssh: SSHDestination = field(repr=False)
    mock_stdout: str = field(repr=False)

    def preview(self) -> DiagnosticPreview:
        destination = {
            "command_line": self.line,
            "host_name": self.host_name,
            "ssh_host": self.ssh.host,
            "ssh_port": self.ssh.port,
            "ssh_username": self.ssh.username,
        }
        fingerprint_data = {
            **destination,
            "command_kind": self.kind,
            "command_ref": self.ref,
            "product": self.product,
            "target_id": str(self.target_id),
            "host_key": self.ssh.host_key,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_data, sort_keys=True).encode()
        ).hexdigest()
        return DiagnosticPreview(**destination, fingerprint=fingerprint)

    def snapshot(self) -> dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "target_id": self.target_id,
            "product": self.product,
            "host_name": self.host_name,
            "ssh_host": self.ssh.host,
            "ssh_port": self.ssh.port,
            "ssh_username": self.ssh.username,
            "command_kind": self.kind,
            "command_ref": self.ref,
            "command_line": self.line,
            "params": self.command.params,
        }


@dataclass(frozen=True)
class RunActor:
    username: str
    user_id: UUID | None
    ip: str | None
    display_name: str

    def audit(self, event: str, **fields: object) -> None:
        audit(
            f"diagnostics.run.{event}",
            username=self.username,
            user_id=self.user_id,
            ip=self.ip,
            **fields,
        )


async def prepare_run(
    settings: Settings, incident_id: UUID, body: DiagnosticPreviewInput
) -> PreparedRun:
    async with session_scope(settings=settings, isolate_memory=True) as session:
        if (
            await session.scalar(select(Incident.id).where(Incident.id == incident_id))
            is None
        ):
            raise run_error(404, "incident_not_found", "インシデントが見つかりません。")
        await _check_run_limit(session, incident_id)
        target = await session.get(DiagnosticTarget, body.target_id)
        if target is None:
            raise run_error(
                404, "diagnostic_target_not_found", "診断の対象が見つかりません。"
            )
        connection = await read_ssh_connection(
            session, target.ssh_connection_id, "diagnostics"
        )
        if connection is None:
            raise run_error(
                404,
                "diagnostic_connection_not_found",
                "診断用の SSH 接続先が見つかりません。",
            )
        if not connection.approved_key:
            raise run_error(
                409,
                "diagnostic_host_key_unapproved",
                "SSH 接続先のホスト鍵を承認してください。",
            )
        try:
            check_ssh_port(settings, connection.port)
        except ValueError as exc:
            raise run_error(422, "diagnostic_port_not_allowed", str(exc)) from None
        private_key = await session.scalar(
            select(SSHCredential.private_key).where(
                SSHCredential.id == connection.credential_id,
                SSHCredential.purpose == "diagnostics",
            )
        )
        if private_key is None:
            raise run_error(
                404,
                "diagnostic_credential_not_found",
                "診断用の SSH 鍵が見つかりません。",
            )

        kind: Literal["builtin", "custom"]
        if isinstance(body.command, BuiltinCommandRef):
            kind, ref = "builtin", body.command.builtin
            definition = BUILTIN_COMMANDS.get(ref)
            if definition is None:
                raise run_error(
                    404,
                    "diagnostic_command_not_found",
                    "診断コマンドが見つかりません。",
                )
            mock_stdout = definition.mock_stdout
        else:
            kind, ref = "custom", str(body.command.custom)
            definition = await session.get(DiagnosticCommand, body.command.custom)
            if definition is None:
                raise run_error(
                    404,
                    "diagnostic_command_not_found",
                    "診断コマンドが見つかりません。",
                )
            mock_stdout = "モックモードのため実行していません\n"

        if definition.product != target.product:
            raise run_error(
                422,
                "diagnostic_product_mismatch",
                "コマンドの製品が対象と一致しません。",
            )
        try:
            line = render_command(
                definition.template, definition.param_definitions, body.params
            )
            params = {
                item["name"]: normalize_parameter(
                    item["type"], body.params[item["name"]]
                )
                for item in definition.param_definitions
            }
            if kind == "custom":
                worker_command = WorkerCommand(
                    custom=CustomCommand(
                        template=definition.template,
                        param_definitions=list(definition.param_definitions),
                    ),
                    params=params,
                )
            else:
                worker_command = WorkerCommand(builtin=ref, params=params)
        except ParameterError as exc:
            raise run_error(
                422,
                "diagnostic_params_invalid",
                [
                    {"parameter": name, "reason": reason}
                    for name, reason in sorted(exc.errors.items())
                ],
            ) from None
        except TemplateError as exc:
            raise run_error(
                422,
                "diagnostic_template_invalid",
                {
                    "reason": exc.reason,
                    "parameter": exc.parameter,
                },
            ) from None
        except (ValidationError, KeyError, TypeError):
            raise run_error(
                422, "diagnostic_template_invalid", {"reason": "invalid_template"}
            ) from None

        return PreparedRun(
            incident_id=incident_id,
            target_id=target.id,
            connection_id=connection.id,
            product=target.product,
            kind=kind,
            ref=ref,
            title=definition.title,
            host_name=target.host_name,
            line=line,
            command=worker_command,
            mock_stdout=mock_stdout,
            ssh=SSHDestination(
                host=connection.host,
                port=connection.port,
                username=connection.username,
                private_key=private_key,
                host_key=connection.approved_key,
            ),
        )


async def _execute(settings: Settings, run: PreparedRun) -> DiagnosticResult:
    if settings.mock_mode:
        return DiagnosticResult(
            executed=False,
            exit_status=0,
            stdout=run.mock_stdout,
            stdout_bytes=len(run.mock_stdout.encode()),
        )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + EXECUTION_TIMEOUT
    worker = CollectorWorker([], label="diagnostics")
    try:
        async with asyncio.timeout_at(deadline - 5):
            hardened = await worker.request(
                {"op": "harden"}, timeout=deadline - loop.time() - 5
            )
            if (
                not isinstance(hardened, dict)
                or type(hardened.get("applied")) is not bool
            ):
                raise CollectorWorkerError("invalid harden response")
            if sys.platform.startswith("linux") and not hardened["applied"]:
                raise CollectorWorkerError("diagnostic worker hardening failed")
            remaining = deadline - loop.time()
            if remaining <= 7:
                raise TimeoutError
            response = await worker.request(
                {
                    "op": "diagnose",
                    "ssh": run.ssh.model_dump(),
                    "product": run.product,
                    "command": run.command.model_dump(exclude_none=True),
                    "deadline_seconds": remaining - 7,
                },
                timeout=remaining - 5,
                auto_start=False,
            )
            result = DiagnosticResult.model_validate(response)
            if result.executed is None or (result.exit_status is None) == (
                result.error_code is None
            ):
                raise CollectorWorkerError("invalid diagnostic result")
            return result
    except TimeoutError:
        return DiagnosticResult(executed=None, error_code="timeout")
    except (CollectorWorkerError, OSError, ValidationError):
        return DiagnosticResult(executed=None, error_code="worker_unavailable")
    finally:
        # 最後の 5 秒を停止に残し、停止の失敗で確定済みの結果を置き換えない。
        try:
            async with asyncio.timeout_at(deadline):
                await worker.kill()
        except TimeoutError:
            logger.warning("診断ワーカーの停止が期限を超えました。")
        except Exception as exc:
            log_diagnostic_exception(logger, "診断ワーカーの停止に失敗しました。", exc)


async def _save_run(
    session: AsyncSession,
    run: PreparedRun,
    result: DiagnosticResult,
    actor: RunActor,
    *,
    started_at: datetime,
    finished_at: datetime,
    elapsed_ms: int,
) -> DiagnosticRunRead:
    if not await lock_incident(session, run.incident_id):
        raise run_error(404, "incident_not_found", "インシデントが見つかりません。")
    await _check_run_limit(session, run.incident_id)
    row = IncidentDiagnosticRun(
        **run.snapshot(),
        command_title=run.title,
        executed=result.executed,
        status=result.status,
        exit_status=result.exit_status,
        error_code=result.error_code,
        stdout=result.stdout,
        stderr=result.stderr,
        stdout_truncated=result.stdout_truncated,
        stderr_truncated=result.stderr_truncated,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_ms=elapsed_ms,
        run_by=actor.display_name,
    )
    outcome = (
        f"終了コード {result.exit_status}"
        if result.error_code is None
        else result.error_code
    )
    saved_at = utcnow()
    await mark_incident_updated(session, run.incident_id, saved_at, actor.display_name)
    session.add_all(
        [
            row,
            IncidentEntry(
                incident_id=run.incident_id,
                kind="diagnostic",
                author=actor.display_name,
                body=f"診断「{run.title}」を {run.host_name} で実行した（{outcome}）",
                created_at=saved_at,
            ),
        ]
    )
    await session.flush()
    return DiagnosticRunRead.model_validate(row)


def rejection_reason(exc: HTTPException) -> str:
    return (exc.headers or {}).get("X-VEA-Error-Code", "diagnostic_rejected")


class DiagnosticRuns:
    """実行枠と、要求から切り離したタスクをアプリ内で保持する。"""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task[DiagnosticRunRead]] = set()
        self.connections: set[UUID] = set()
        self._saving: set[asyncio.Task[None]] = set()
        self.stopping = False

    def start(
        self, settings: Settings, run: PreparedRun, actor: RunActor
    ) -> asyncio.Task[DiagnosticRunRead]:
        if (
            self.stopping
            or len(self.connections) >= 2
            or run.connection_id in self.connections
        ):
            raise run_error(409, "diagnostic_busy", "診断の実行枠に空きがありません。")
        self.connections.add(run.connection_id)
        task = asyncio.create_task(self._run(settings, run, actor))
        self.tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task[DiagnosticRunRead]) -> None:
        self.tasks.discard(task)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None and not isinstance(exc, HTTPException):
                log_diagnostic_exception(logger, "診断タスクが失敗しました。", exc)

    def _save_done(self, task: asyncio.Task[None]) -> None:
        self._saving.discard(task)
        if not task.cancelled():
            task.exception()

    async def shutdown(self) -> None:
        self.stopping = True
        if self.tasks:
            _, pending = await asyncio.wait(tuple(self.tasks), timeout=SHUTDOWN_TIMEOUT)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run(
        self, settings: Settings, run: PreparedRun, actor: RunActor
    ) -> DiagnosticRunRead:
        fields = {**run.snapshot(), "ssh_connection_id": run.connection_id}
        started_at = utcnow()
        loop = asyncio.get_running_loop()
        start = loop.time()
        saved: DiagnosticRunRead | None = None
        try:
            actor.audit("started", **fields)
            result = await _execute(settings, run)
            finished_at = utcnow()
            elapsed_ms = int((loop.time() - start) * 1000)
            fields.update(
                status=result.status,
                executed="null" if result.executed is None else result.executed,
                exit_status="null"
                if result.exit_status is None
                else result.exit_status,
                error_code=result.error_code or "null",
                elapsed_ms=elapsed_ms,
                stdout_bytes=result.stdout_bytes,
                stderr_bytes=result.stderr_bytes,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
            )
            save_deadline = asyncio.timeout(SAVE_TIMEOUT)

            async def save() -> None:
                nonlocal saved
                async with open_session(settings, isolate_memory=True) as session:
                    row = await _save_run(
                        session,
                        run,
                        result,
                        actor,
                        started_at=started_at,
                        finished_at=finished_at,
                        elapsed_ms=elapsed_ms,
                    )
                    if save_deadline.expired():
                        raise TimeoutError
                    task = asyncio.current_task()
                    if task is not None and task.cancelling():
                        raise asyncio.CancelledError
                    await session.commit()
                    # commit 後の監査までに取り消しが入らないよう await を挟まない。
                    saved = row
                    actor.audit("finished", **fields, run_id=row.id)

            try:
                async with save_deadline:
                    saving = asyncio.create_task(save())
                    self._saving.add(saving)
                    saving.add_done_callback(self._save_done)
                    # DB ドライバが取り消し後の後片付けに時間をかけても、要求と枠を解放する。
                    try:
                        await asyncio.shield(saving)
                    finally:
                        if not saving.done():
                            saving.cancel()
            except HTTPException as exc:
                actor.audit("discarded", **fields, reason=rejection_reason(exc))
                raise
            except Exception as exc:
                reason = (
                    "save_timeout"
                    if isinstance(exc, TimeoutError) and save_deadline.expired()
                    else "save_failed"
                )
                _log_save_failure(reason, exc)
                if saved is None:
                    actor.audit("discarded", **fields, reason=reason)
                    raise run_error(
                        503,
                        "diagnostic_save_failed",
                        "診断の結果を保存できませんでした。",
                    ) from None
            assert saved is not None
            return saved
        except asyncio.CancelledError:
            if saved is None:
                actor.audit("aborted", **fields)
            raise
        except HTTPException:
            raise
        except Exception as exc:
            actor.audit("discarded", **fields, reason="internal_error")
            log_diagnostic_exception(
                logger, "診断の実行中に予期しないエラーが発生しました。", exc
            )
            raise run_error(
                500, "diagnostic_internal_error", "診断を実行できませんでした。"
            ) from None
        finally:
            self.connections.discard(run.connection_id)
