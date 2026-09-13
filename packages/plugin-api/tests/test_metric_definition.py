"""``MetricDefinition.at()`` が定義から値を補うこと。

これで消える罠は 2 つある。メトリクスキーを manifest とサンプルの両方に書く二重記述と、
``datetime.now()`` を ``timezone.utc`` なしで書いてバッチ全体を拒否させる事故である。
"""

from __future__ import annotations

from datetime import datetime, timezone

from vcenter_event_assistant_plugin_api import MetricDefinition, limits

TEMPERATURE = MetricDefinition(
    key="example.host.temperature_c",
    display_name="Host temperature",
    unit="C",
    entity_type="HostSystem",
)


def test_at_fills_key_and_entity_type_from_the_definition() -> None:
    sample = TEMPERATURE.at(entity_moid="host-1", entity_name="esxi-01", value=31.5)
    assert sample.metric_key == TEMPERATURE.key
    assert sample.entity_type == "HostSystem"


def test_at_defaults_to_an_aware_timestamp() -> None:
    sample = TEMPERATURE.at(entity_moid="host-1", entity_name="esxi-01", value=1)
    assert sample.sampled_at.tzinfo is not None


def test_at_accepts_an_explicit_timestamp() -> None:
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sample = TEMPERATURE.at(
        entity_moid="host-1", entity_name="esxi-01", value=1, sampled_at=when
    )
    assert sample.sampled_at == when


def test_at_coerces_the_value_to_float() -> None:
    sample = TEMPERATURE.at(entity_moid="host-1", entity_name="esxi-01", value=7)
    assert isinstance(sample.value, float)


def test_at_allows_overriding_entity_type() -> None:
    sample = TEMPERATURE.at(
        entity_moid="vm-1", entity_name="vm", value=1, entity_type="VirtualMachine"
    )
    assert sample.entity_type == "VirtualMachine"


def test_at_does_not_silently_truncate() -> None:
    """値を勝手に変えない。超過は check_batch が warning として報告する。"""
    long_name = "x" * (limits.MAX_ENTITY_NAME + 10)
    sample = TEMPERATURE.at(entity_moid="host-1", entity_name=long_name, value=1)
    assert sample.entity_name == long_name
