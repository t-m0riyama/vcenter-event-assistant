"""診断設定の変更を確定させてから監査ログに記録する。"""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.api.auth_deps import Principal
from vcenter_event_assistant.auth.audit import audit


async def commit_audit(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    event: str,
    **fields: object,
) -> None:
    await session.commit()
    audit(
        f"diagnostics.{event}",
        username=principal.username,
        user_id=principal.user_id,
        ip=request.client.host if request.client else None,
        **fields,
    )
