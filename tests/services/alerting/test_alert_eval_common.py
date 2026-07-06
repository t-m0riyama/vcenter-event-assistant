"""alert_eval_common のユーティリティテスト。"""

from __future__ import annotations

import uuid

from vcenter_event_assistant.services.alerting.alert_eval_common import (
    is_vcenter_scoped_context_key,
    metric_context_key,
)


def test_metric_context_key_includes_vcenter_id() -> None:
    vc_id = uuid.uuid4()
    assert metric_context_key(vc_id, "host-10") == f"{vc_id}:host-10"


def test_is_vcenter_scoped_context_key() -> None:
    vc_id = uuid.uuid4()
    assert is_vcenter_scoped_context_key(f"{vc_id}:host-10") is True
    assert is_vcenter_scoped_context_key("host-10") is False
    assert is_vcenter_scoped_context_key("vim.event.Foo") is False
