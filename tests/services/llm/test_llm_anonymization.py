"""llm_anonymization の単体テスト。"""

from __future__ import annotations

import re

import pytest

from vcenter_event_assistant.services.llm.llm_anonymization import (
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


def test_anonymize_moid_fields_and_message() -> None:
    raw = {
        "message": "[vm-1] vm-101 myvm-1 vm-1a vm-1_backup [custom-id] mycustom-id host-45",
        "series": [
            {"entity_name": "vm-1", "entity_moid": "vm-1"},
            {"entity_moid": "custom-id"},
            {"entity_moid": None},
            {"entity_name": "host", "entity_moid": "host-45"},
        ],
    }

    out, reverse_map = anonymize_json_like(raw)

    assert out["series"] == [
        {"entity_name": "__LM_MOID_001__", "entity_moid": "__LM_MOID_001__"},
        {"entity_moid": "__LM_MOID_002__"},
        {"entity_moid": None},
        {"entity_name": "__LM_ENTITY_001__", "entity_moid": "__LM_MOID_003__"},
    ]
    assert out["message"] == (
        "[__LM_MOID_001__] __LM_MOID_004__ myvm-1 vm-1a vm-1_backup "
        "[__LM_MOID_002__] mycustom-id __LM_MOID_003__"
    )
    assert deanonymize_text(out["message"], reverse_map) == raw["message"]


def test_anonymize_plain_text_detects_moids_without_overlapping_other_replacements() -> None:
    a = LlmAnonymizer()
    host = a.token_for("entity", "host-45.example")
    original = (
        "host-45.example at 192.0.2.1: host-45, domain-c7, group-v3, group-p8, "
        "group-9, resgroup-v12, datastore-3, network-o4, snapshot-5, alarm-6; "
        "myvm-12 vm-12a vapp-12 group-x3"
    )

    text = anonymize_plain_text(original, a)

    assert text == (
        f"{host} at __LM_IP_001__: __LM_MOID_001__, __LM_MOID_002__, __LM_MOID_003__, "
        "__LM_MOID_004__, __LM_MOID_005__, __LM_MOID_006__, __LM_MOID_007__, "
        "__LM_MOID_008__, __LM_MOID_009__, __LM_MOID_010__; myvm-12 vm-12a vapp-12 group-x3"
    )
    assert deanonymize_text(text, a.reverse_map) == original


@pytest.mark.parametrize("name", ["vm-01", "vm-101"])
def test_moid_shaped_entity_name_still_allows_partial_replacement(name: str) -> None:
    out, _ = anonymize_json_like({
        "entity_name": name,
        "entity_moid": "vm-42",
        "message": f"Clone {name} to {name}-clone, {name}_old",
    })

    token = out["entity_name"]
    assert token == "__LM_ENTITY_001__"
    assert out["message"] == f"Clone {token} to {token}-clone, {token}_old"


@pytest.mark.parametrize("short", ["host-01", "host-1"])
def test_moid_shaped_short_name_still_uses_fqdn_alias(short: str) -> None:
    out, _ = anonymize_json_like({"entity_name": f"{short}.lab.local", "message": f"{short} is down"})

    assert out["message"] == f"{out['entity_name']} is down"


def test_registered_user_takes_priority_over_moid_pattern() -> None:
    out, _ = anonymize_json_like({"user_name": "host-1", "message": "host-1 signed in"})

    assert out["message"] == "__LM_USER_001__ signed in"


def test_unregistered_moid_detection_ignores_leading_zero() -> None:
    a = LlmAnonymizer()

    assert anonymize_plain_text("vm-01 host-01 vm-0 vm-1001", a) == "vm-01 host-01 vm-0 __LM_MOID_001__"


def test_short_registered_moid_is_replaced_only_in_its_field() -> None:
    out, reverse_map = anonymize_json_like({"entity_moid": "x", "message": "x, xx"})

    assert deanonymize_text(out["entity_moid"], reverse_map) == "x"
    assert out["message"] == "x, xx"


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


def test_anonymize_plain_text_does_not_replace_generated_tokens() -> None:
    a = LlmAnonymizer()
    host = "esxi-prod.example"
    host_token = a.token_for("entity", host)
    other_token = a.token_for("entity", "LM.lab.example")
    a.share_token_with("entity", "LM", "LM.lab.example")
    ip = "192.0.2.1"
    ip_token = a.token_for("ip", ip)

    text = anonymize_plain_text(f"{host} and LM at {ip}", a)

    assert text == f"{host_token} and {other_token} at {ip_token}"
    assert deanonymize_text(text, a.reverse_map) == f"{host} and LM.lab.example at {ip}"


def test_anonymize_plain_text_prioritizes_longer_overlapping_name() -> None:
    a = LlmAnonymizer()
    host = "esxi01.prod.example"
    host_token = a.token_for("entity", host)
    other_token = a.token_for("entity", "backup-esxi01.lab.example")
    a.share_token_with("entity", "backup-esxi01", "backup-esxi01.lab.example")

    text = anonymize_plain_text(f"backup-{host} and backup-esxi01", a)

    assert text == f"backup-{host_token} and {other_token}"


def test_anonymize_plain_text_finds_match_after_rejected_overlap() -> None:
    a = LlmAnonymizer()
    first = a.token_for("entity", "xyzab")
    second = a.token_for("entity", "aba")

    assert anonymize_plain_text("xyzababa", a) == first + second


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


def test_anonymize_for_llm_extra_vcenter_strings_tokenize_markdown() -> None:
    """JSON に無い登録 vCenter 文字列も Markdown から除去できる。"""
    ctx: dict = {"digest_context": {"total_events": 0}}
    md = "接続先 vcenter01.example.com と短縮 vc01 のメモ"
    extra = ["vcenter01.example.com", "vc01"]
    ctx2, md2, rev = anonymize_for_llm(ctx, md, extra_vcenter_strings=extra)
    assert "vcenter01.example.com" not in md2
    assert "vc01" not in md2
    assert deanonymize_text(md2, rev) == md


def test_anonymize_chat_for_llm_extra_vcenter_strings_in_messages() -> None:
    from vcenter_event_assistant.services.llm.llm_anonymization import anonymize_chat_for_llm

    payload = {"digest_context": {"total_events": 0}}
    contents = ["MyDisplay と vcenter02.lab.local を確認"]
    extra = ["MyDisplay", "vcenter02.lab.local", "vcenter02"]
    _pl, out_contents, _att, _filenames, rev = anonymize_chat_for_llm(
        payload,
        contents,
        extra_vcenter_strings=extra,
    )
    assert "MyDisplay" not in out_contents[0]
    assert "vcenter02.lab.local" not in out_contents[0]
    assert "vcenter02" not in out_contents[0]
    assert deanonymize_text(out_contents[0], rev) == contents[0]


def test_anonymize_chat_for_llm_tokenizes_short_hostname_when_entity_name_is_fqdn() -> None:
    """period_metrics の entity_name が FQDN のとき、第1ラベル（短縮名）も会話からトークン化する。"""
    from vcenter_event_assistant.services.llm.llm_anonymization import anonymize_chat_for_llm

    payload = {
        "digest_context": {"total_events": 0},
        "period_metrics": {
            "cpu": [
                {
                    "entity_name": "mini5.moriyama.internal",
                    "entity_moid": "host-123",
                    "metric_key": "host.cpu.usage_pct",
                    "series": [],
                }
            ]
        },
    }
    contents = ["mini5のCPU使用率が最も高い時間帯を教えて。"]
    _pl, out_contents, _att, _filenames, rev = anonymize_chat_for_llm(payload, contents, extra_vcenter_strings=None)
    assert "mini5" not in out_contents[0]
    assert "mini5.moriyama.internal" not in str(_pl)
    tok_in_json = _pl["period_metrics"]["cpu"][0]["entity_name"]
    m = re.search(r"__LM_ENTITY_\d{3}__", out_contents[0])
    assert m is not None
    assert m.group(0) == tok_in_json
    # 短縮名と FQDN を同一トークンにまとめたため、逆変換の代表は FQDN になる
    assert (
        deanonymize_text(out_contents[0], rev)
        == "mini5.moriyama.internalのCPU使用率が最も高い時間帯を教えて。"
    )


def test_settings_llm_anonymization_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """``LLM_ANONYMIZATION_ENABLED`` でオンオフできること。"""
    from vcenter_event_assistant.settings import Settings

    monkeypatch.delenv("LLM_ANONYMIZATION_ENABLED", raising=False)
    assert Settings(database_url="sqlite+aiosqlite:///:memory:").llm_anonymization_enabled is True

    monkeypatch.setenv("LLM_ANONYMIZATION_ENABLED", "false")
    assert Settings(database_url="sqlite+aiosqlite:///:memory:").llm_anonymization_enabled is False
