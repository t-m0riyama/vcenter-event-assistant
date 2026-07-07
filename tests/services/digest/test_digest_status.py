"""digest_status のユニットテスト。"""

from vcenter_event_assistant.services.digest.digest_status import (
    DIGEST_STATUS_OK,
    DIGEST_STATUS_OK_LLM_FAILED,
    resolve_digest_status_after_llm,
)


def test_resolve_digest_status_after_llm_ok_when_no_error() -> None:
    assert resolve_digest_status_after_llm(llm_error_message=None) == DIGEST_STATUS_OK
    assert resolve_digest_status_after_llm(llm_error_message="") == DIGEST_STATUS_OK


def test_resolve_digest_status_after_llm_failed_when_error_present() -> None:
    assert (
        resolve_digest_status_after_llm(llm_error_message="LLM 要約は省略（timeout）")
        == DIGEST_STATUS_OK_LLM_FAILED
    )
