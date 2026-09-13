"""``plugin_api.limits`` の定数が DB の列定義と一致していること。

定数は ``db/models.py`` を写したものなので、片方だけ変わると作者に嘘を教えることになる。
列を広げたときに気づけるよう、introspection で突き合わせる。
"""

from __future__ import annotations

import pytest
from sqlalchemy import Integer, String
from vcenter_event_assistant_plugin_api import limits

from vcenter_event_assistant.db.models import EventRecord, MetricSample


def _length(model, column_name: str) -> int:
    column = model.__table__.columns[column_name]
    assert isinstance(column.type, String), f"{column_name} は String ではない"
    assert column.type.length is not None, f"{column_name} に長さ制限がない"
    return column.type.length


@pytest.mark.parametrize(
    ("model", "column", "constant"),
    [
        (MetricSample, "collector_id", limits.MAX_PLUGIN_ID),
        (MetricSample, "metric_key", limits.MAX_METRIC_KEY),
        (MetricSample, "entity_type", limits.MAX_METRIC_ENTITY_TYPE),
        (MetricSample, "entity_moid", limits.MAX_ENTITY_MOID),
        (MetricSample, "entity_name", limits.MAX_ENTITY_NAME),
        (EventRecord, "collector_id", limits.MAX_PLUGIN_ID),
        (EventRecord, "event_type", limits.MAX_EVENT_TYPE),
        (EventRecord, "severity", limits.MAX_SEVERITY),
        (EventRecord, "user_name", limits.MAX_USER_NAME),
        (EventRecord, "entity_name", limits.MAX_ENTITY_NAME),
        (EventRecord, "entity_type", limits.MAX_EVENT_ENTITY_TYPE),
    ],
)
def test_string_limits_match_the_columns(model, column: str, constant: int) -> None:
    assert _length(model, column) == constant


def test_vmware_key_is_still_a_32_bit_integer_column() -> None:
    """``stable_int63`` を推奨できない理由そのもの。

    ``BigInteger`` へ広げたら、``limits`` の範囲と作者向けの案内も同時に更新する。
    """
    column = EventRecord.__table__.columns["vmware_key"]
    assert isinstance(column.type, Integer)
    assert column.type.__class__ is Integer, "BigInteger 化したら limits も更新する"
    assert limits.VMWARE_KEY_MAX == 2**31 - 1


def test_metric_dedup_key_matches_the_duplicate_warning() -> None:
    """``check_batch`` の duplicate_dedup_key はこの一意制約を前提にしている。"""
    constraint = next(
        c
        for c in MetricSample.__table__.constraints
        if getattr(c, "name", None) == "uq_metric_sample_point"
    )
    assert [c.name for c in constraint.columns] == [
        "vcenter_id",
        "sampled_at",
        "entity_moid",
        "metric_key",
    ]


def test_event_dedup_key_matches_the_duplicate_warning() -> None:
    constraint = next(
        c
        for c in EventRecord.__table__.constraints
        if getattr(c, "name", None) == "uq_event_collector_vmware_key"
    )
    assert [c.name for c in constraint.columns] == [
        "vcenter_id",
        "collector_id",
        "vmware_key",
    ]
