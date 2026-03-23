"""ダイジェスト 1 回分の生成と ``DigestRecord`` への保存。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import DigestRecord
from vcenter_event_assistant.services.digest_context import build_digest_context
from vcenter_event_assistant.services.digest_llm import augment_digest_with_llm
from vcenter_event_assistant.services.digest_markdown import render_digest_markdown
from vcenter_event_assistant.settings import Settings, get_settings


async def run_digest_once(
    session: AsyncSession,
    *,
    kind: str,
    from_utc: datetime,
    to_utc: datetime,
    settings: Settings | None = None,
) -> DigestRecord:
    """
    集約 → テンプレート Markdown →（任意）LLM 追記 → ``DigestRecord`` を ``session`` に追加する。

    呼び出し側で commit する（``get_session`` 依存ルートと同様）。
    """
    s = settings or get_settings()
    ctx = await build_digest_context(session, from_utc, to_utc)
    try:
        md = render_digest_markdown(ctx, kind=kind, settings=s)
    except Exception as e:
        err = ("digest template: " + str(e))[:2000]
        row = DigestRecord(
            period_start=from_utc,
            period_end=to_utc,
            kind=kind,
            body_markdown="",
            status="error",
            error_message=err,
            llm_model=None,
        )
        session.add(row)
        await session.flush()
        return row

    body, llm_err = await augment_digest_with_llm(s, context=ctx, template_markdown=md)

    has_key = bool((s.llm_api_key or "").strip())
    llm_model_val = s.llm_model if has_key and llm_err is None else None

    row = DigestRecord(
        period_start=from_utc,
        period_end=to_utc,
        kind=kind,
        body_markdown=body,
        status="ok",
        error_message=llm_err,
        llm_model=llm_model_val,
    )
    session.add(row)
    await session.flush()
    return row
