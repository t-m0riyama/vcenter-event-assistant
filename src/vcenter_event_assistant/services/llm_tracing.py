"""LangSmith / RunnableConfig 用のタグ・metadata・コールバック組み立て。"""

from __future__ import annotations

from typing import Literal

from langchain_core.tracers.langchain import LangChainTracer
from langchain_core.runnables import RunnableConfig
from langsmith import Client

from vcenter_event_assistant.settings import Settings

RunKind = Literal["period_chat", "digest"]


def build_llm_runnable_config(
    settings: Settings,
    *,
    run_kind: RunKind,
    vcenter_id: str | None = None,
    digest_kind: str | None = None,
) -> RunnableConfig:
    """
    LLM 呼び出しに渡す ``RunnableConfig`` を組み立てる。

    ``langsmith_tracing_enabled`` かつ ``langsmith_api_key`` が設定されているときだけ
    ``LangChainTracer`` を ``callbacks`` に載せる。それ以外は tags / metadata のみ。
    """
    tags: list[str] = ["vea", run_kind]
    metadata: dict[str, str | bool] = {
        "run_kind": run_kind,
        "llm_provider": str(settings.llm_provider),
        "llm_model": settings.llm_model,
    }
    if vcenter_id is not None:
        metadata["vcenter_id"] = vcenter_id
    if run_kind == "digest" and digest_kind is not None:
        metadata["digest_kind"] = digest_kind

    out: RunnableConfig = {"tags": tags, "metadata": metadata}

    key = (settings.langsmith_api_key or "").strip()
    if not settings.langsmith_tracing_enabled or not key:
        return out

    client_kw: dict[str, str] = {"api_key": key}
    api_url = (settings.langsmith_endpoint or "").strip()
    if api_url:
        client_kw["api_url"] = api_url
    client = Client(**client_kw)

    tracer_kw: dict[str, object] = {"client": client}
    project = (settings.langsmith_project or "").strip()
    if project:
        tracer_kw["project_name"] = project

    out["callbacks"] = [LangChainTracer(**tracer_kw)]
    return out
