"""vcenter_labels: LLM 匿名化用の vCenter 文字列列挙のテスト。"""

from __future__ import annotations

import pytest

from vcenter_event_assistant.services.vcenter_labels import (
    vcenter_strings_for_anonymization,
)


def test_vcenter_strings_includes_name_and_host() -> None:
    out = vcenter_strings_for_anonymization("Prod-VC", "vcenter01.example.com")
    assert out == ["Prod-VC", "vcenter01.example.com", "vcenter01"]


def test_vcenter_strings_fqdn_short_not_duplicated_when_same_as_name() -> None:
    """第1ラベルが表示名と同一なら重複しない。"""
    out = vcenter_strings_for_anonymization("vcenter01", "vcenter01.example.com")
    assert out == ["vcenter01", "vcenter01.example.com"]


def test_vcenter_strings_no_short_for_single_label_host() -> None:
    out = vcenter_strings_for_anonymization("x", "nohyphen")
    assert out == ["x", "nohyphen"]


def test_vcenter_strings_ipv4_host_no_extra_label() -> None:
    out = vcenter_strings_for_anonymization("Label", "203.0.113.10")
    assert out == ["Label", "203.0.113.10"]


def test_vcenter_strings_empty_name_host_only() -> None:
    out = vcenter_strings_for_anonymization("", "a.b.c")
    assert out == ["a.b.c", "a"]


def test_vcenter_strings_dedupes_name_equals_host() -> None:
    out = vcenter_strings_for_anonymization("same.example.com", "same.example.com")
    assert out == ["same.example.com"]


@pytest.mark.asyncio
async def test_load_all_vcenter_anonymization_strings_merges_rows() -> None:
    from vcenter_event_assistant.db.models import VCenter
    from vcenter_event_assistant.db.session import get_session_factory
    from vcenter_event_assistant.services.vcenter_labels import load_all_vcenter_anonymization_strings

    factory = get_session_factory()
    async with factory() as session:
        session.add_all(
            [
                VCenter(name="A", host="vc-a.lab.local", username="u", password="p"),
                VCenter(name="B", host="203.0.113.1", username="u", password="p"),
            ],
        )
        await session.commit()

    async with factory() as session:
        out = await load_all_vcenter_anonymization_strings(session)

    assert "A" in out
    assert "vc-a.lab.local" in out
    assert "vc-a" in out
    assert "B" in out
    assert "203.0.113.1" in out
    assert out.index("A") < out.index("B")

