"""llm_anonymization の単体テスト。"""

from __future__ import annotations

import pytest

from vcenter_event_assistant.services.llm_anonymization import (
    LlmAnonymizer,
    anonymize_for_llm,
    anonymize_json_like,
    anonymize_plain_text,
    deanonymize_text,
)


def test_same_value_gets_same_token_per_category() -> None:
    a = LlmAnonymizer()
    t1 = a.token_for("host", "esxi-01.lab.local")
    t2 = a.token_for("host", "esxi-01.lab.local")
    t3 = a.token_for("host", "esxi-02.lab.local")
    assert t1 == t2
    assert t1 != t3
    assert t1.startswith("__LM_HOST_")


def test_deanonymize_restores_order_longest_token_first() -> None:
    a = LlmAnonymizer()
    x = a.token_for("host", "aa")
    y = a.token_for("host", "a")  # 別トークン
    mixed = f"see {y} and {x}"
    assert deanonymize_text(mixed, a.reverse_map) == "see a and aa"


def test_anonymize_dict_replaces_entity_name_and_message() -> None:
    raw = {
        "top_notable_event_groups": [
            {
                "event_type": "vim.event.Event",
                "entity_name": "VM-DB-01",
                "message": "User root@192.168.1.10 logged in on VM-DB-01",
            }
        ]
    }
    out, rev = anonymize_json_like(raw)
    assert out["top_notable_event_groups"][0]["entity_name"] != "VM-DB-01"
    assert "VM-DB-01" not in str(out)
    assert (
        deanonymize_text(out["top_notable_event_groups"][0]["message"], rev)
        == raw["top_notable_event_groups"][0]["message"]
    )


def test_anonymize_period_metrics_entity_name() -> None:
    raw = {
        "cpu": [
            {
                "entity_name": "esxi-host-01.prod",
                "entity_moid": "host-7",
                "metric_key": "host.cpu.usage_pct",
                "series": [],
            }
        ]
    }
    out, rev = anonymize_json_like(raw)
    assert out["cpu"][0]["entity_name"] != "esxi-host-01.prod"
    assert "esxi-host-01.prod" not in str(out)
    assert deanonymize_text(out["cpu"][0]["entity_name"], rev) == "esxi-host-01.prod"


def test_message_replaces_ipv4() -> None:
    raw = {
        "top_notable_event_groups": [
            {
                "event_type": "vim.event.Event",
                "message": "connection from 203.0.113.10 timed out",
            }
        ]
    }
    out, rev = anonymize_json_like(raw)
    assert "203.0.113.10" not in out["top_notable_event_groups"][0]["message"]
    assert (
        deanonymize_text(out["top_notable_event_groups"][0]["message"], rev)
        == raw["top_notable_event_groups"][0]["message"]
    )


def test_anonymize_plain_text_uses_shared_anonymizer() -> None:
    a = LlmAnonymizer()
    a.token_for("entity", "HOST-A")
    s = anonymize_plain_text("HOST-A and HOST-A", a)
    assert "HOST-A" not in s
    assert deanonymize_text(s, a.reverse_map) == "HOST-A and HOST-A"


def test_anonymize_json_like_replaces_vcenter_label() -> None:
    raw = {
        "high_cpu_hosts": [
            {
                "vcenter_label": "MyVC-Display",
                "entity_name": "h",
                "vcenter_id": "00000000-0000-0000-0000-000000000001",
            }
        ]
    }
    out, rev = anonymize_json_like(raw)
    assert "MyVC-Display" not in str(out)
    lbl = out["high_cpu_hosts"][0]["vcenter_label"]
    assert deanonymize_text(lbl, rev) == "MyVC-Display"


def test_anonymize_for_llm_shared_mapping_between_json_and_markdown() -> None:
    ctx = {"rows": [{"entity_name": "secret-esxi"}]}
    md = "ホスト secret-esxi のメモ"
    ctx2, md2, rev = anonymize_for_llm(ctx, md)
    assert "secret-esxi" not in str(ctx2)
    assert "secret-esxi" not in md2
    assert deanonymize_text(md2, rev) == md


def test_settings_llm_anonymization_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """``LLM_ANONYMIZATION_ENABLED`` でオンオフできること。"""
    from vcenter_event_assistant.settings import Settings

    monkeypatch.delenv("LLM_ANONYMIZATION_ENABLED", raising=False)
    assert Settings(database_url="sqlite+aiosqlite:///:memory:").llm_anonymization_enabled is True

    monkeypatch.setenv("LLM_ANONYMIZATION_ENABLED", "false")
    assert Settings(database_url="sqlite+aiosqlite:///:memory:").llm_anonymization_enabled is False
