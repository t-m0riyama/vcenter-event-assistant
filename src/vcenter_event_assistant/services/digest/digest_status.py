"""ダイジェスト ``DigestRecord.status`` の定数と解決ヘルパー。"""

from __future__ import annotations

DIGEST_STATUS_OK = "ok"
DIGEST_STATUS_ERROR = "error"
DIGEST_STATUS_OK_LLM_FAILED = "ok_llm_failed"


def resolve_digest_status_after_llm(*, llm_error_message: str | None) -> str:
    """
    テンプレート生成成功後の保存用 ``status`` を決める。

    LLM 追記に失敗した場合は ``ok_llm_failed``（本文はテンプレートのみ）。
    """
    if llm_error_message:
        return DIGEST_STATUS_OK_LLM_FAILED
    return DIGEST_STATUS_OK
