"""検証規則が「アプリが実際に拒否する集合」と一致していること。

このモジュールの要点は、error のメッセージを**逐語で固定する**ことである。アプリ側の
``runtime._validate_batch`` と ``registry._validate_plugin`` はこの実装を呼ぶだけになった
ため、ここが振る舞いの正本になる。文言が変わると管理画面の表示も変わる。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from vcenter_event_assistant_plugin_api import (
    CollectionBatch,
    CollectorManifest,
    EventInput,
    MetricDefinition,
    MetricSampleInput,
)
from vcenter_event_assistant_plugin_api import limits
from vcenter_event_assistant_plugin_api.validation import (
    BatchValidationError,
    ManifestValidationError,
    check_batch,
    check_manifest,
    manifest_error_message,
    raise_for_issues,
    validate_batch,
    validate_manifest,
)

KEY = "example.host.temperature_c"


def _manifest(**overrides) -> CollectorManifest:
    base = dict(
        id="example.host.temperature",
        display_name="Example",
        version="1.0.0",
        data_kinds=frozenset({"metric"}),
        metric_definitions=(MetricDefinition(KEY, "Temp", "C", "HostSystem"),),
    )
    base.update(overrides)
    return CollectorManifest(**base)  # type: ignore[arg-type]


def _sample(**overrides) -> MetricSampleInput:
    base = dict(
        sampled_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        entity_type="HostSystem",
        entity_moid="host-1",
        entity_name="esxi-01",
        metric_key=KEY,
        value=42.5,
    )
    base.update(overrides)
    return MetricSampleInput(**base)  # type: ignore[arg-type]


def _event(**overrides) -> EventInput:
    base = dict(
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        event_type="VmPoweredOnEvent",
        message="powered on",
        vmware_key=1234,
    )
    base.update(overrides)
    return EventInput(**base)  # type: ignore[arg-type]


def _codes(issues, severity=None):
    return [i.code for i in issues if severity is None or i.severity == severity]


# --- manifest: アプリが拒否する条件と文言 ---------------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": "Example"}, "invalid plugin id"),
        ({"id": ""}, "invalid plugin id"),
        ({"api_version": 2}, "unsupported plugin API version 2"),
        (
            {"default_interval_seconds": 9},
            "default interval must be at least 10 seconds",
        ),
        ({"data_kinds": frozenset()}, "data_kinds must contain event and/or metric"),
        (
            {"data_kinds": frozenset({"alarm"})},
            "data_kinds must contain event and/or metric",
        ),
        (
            {
                "metric_definitions": (
                    MetricDefinition(KEY, "A", "C", "HostSystem"),
                    MetricDefinition(KEY, "B", "C", "HostSystem"),
                )
            },
            "duplicate metric key in manifest",
        ),
        (
            {"metric_definitions": ()},
            "metric collector must declare metric definitions",
        ),
        (
            {"metric_definitions": (MetricDefinition("x" * 257, "A", "C", "H"),)},
            "metric keys must be 1..256 characters",
        ),
        (
            {"metric_definitions": (MetricDefinition("", "A", "C", "H"),)},
            "metric keys must be 1..256 characters",
        ),
    ],
)
def test_manifest_error_messages_are_fixed(overrides, message) -> None:
    assert manifest_error_message(_manifest(**overrides)) == message


def test_a_valid_manifest_has_no_errors() -> None:
    assert manifest_error_message(_manifest()) is None
    validate_manifest(_manifest())


def test_validate_manifest_carries_the_issues() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest(_manifest(api_version=2))
    assert excinfo.value.issues[0].code == "unsupported_api_version"


def test_event_only_manifest_needs_no_metric_definitions() -> None:
    manifest = _manifest(data_kinds=frozenset({"event"}), metric_definitions=())
    assert manifest_error_message(manifest) is None


def test_declaring_metrics_without_the_metric_kind_warns() -> None:
    """宣言したキーは使われず、実際に返した瞬間に拒否される。"""
    manifest = _manifest(data_kinds=frozenset({"event"}))
    assert manifest_error_message(manifest) is None
    assert "unused_metric_definitions" in _codes(check_manifest(manifest), "warning")


# --- batch: アプリが拒否する条件と文言 ------------------------------------


@pytest.mark.parametrize(
    ("batch", "message"),
    [
        (
            CollectionBatch(events=(_event(),)),
            "collector emitted undeclared event data",
        ),
        (
            CollectionBatch(metrics=(_sample(metric_key="other.key"),)),
            "undeclared metric key: other.key",
        ),
        (
            CollectionBatch(metrics=(_sample(value=float("nan")),)),
            f"non-finite metric value: {KEY}",
        ),
        (
            CollectionBatch(metrics=(_sample(value=float("inf")),)),
            f"non-finite metric value: {KEY}",
        ),
        (
            CollectionBatch(metrics=(_sample(sampled_at=datetime(2026, 1, 1)),)),
            "metric sampled_at must be timezone-aware",
        ),
    ],
)
def test_batch_error_messages_are_fixed(batch, message) -> None:
    with pytest.raises(BatchValidationError) as excinfo:
        validate_batch(_manifest(), batch)
    assert excinfo.value.issues[0].message == message


def test_undeclared_metric_data_is_rejected() -> None:
    manifest = _manifest(data_kinds=frozenset({"event"}), metric_definitions=())
    with pytest.raises(BatchValidationError) as excinfo:
        validate_batch(manifest, CollectionBatch(metrics=(_sample(),)))
    assert excinfo.value.issues[0].message == "collector emitted undeclared metric data"


def test_naive_event_occurred_at_is_rejected() -> None:
    manifest = _manifest(data_kinds=frozenset({"event"}), metric_definitions=())
    batch = CollectionBatch(events=(_event(occurred_at=datetime(2026, 1, 1)),))
    with pytest.raises(BatchValidationError) as excinfo:
        validate_batch(manifest, batch)
    assert excinfo.value.issues[0].message == "event occurred_at must be timezone-aware"


def test_a_valid_batch_passes() -> None:
    validate_batch(_manifest(), CollectionBatch(metrics=(_sample(),)))
    assert check_batch(_manifest(), CollectionBatch(metrics=(_sample(),))) == ()


def test_issues_carry_the_position_in_the_batch() -> None:
    batch = CollectionBatch(metrics=(_sample(), _sample(metric_key="other.key")))
    issues = check_batch(_manifest(), batch)
    assert issues[0].index == 1
    assert issues[0].field == "metric_key"


# --- warning: アプリは拒否しないが静かにデータが失われるもの ---------------


def test_warnings_do_not_make_validate_batch_raise() -> None:
    """受理・拒否の境界を変えないこと。warning を error に昇格させてはならない。"""
    batch = CollectionBatch(metrics=(_sample(entity_name="x" * 2000),))
    validate_batch(_manifest(), batch)  # 送出しない
    assert "field_too_long" in _codes(check_batch(_manifest(), batch), "warning")


def test_over_length_fields_are_reported() -> None:
    batch = CollectionBatch(
        metrics=(_sample(entity_moid="m" * (limits.MAX_ENTITY_MOID + 1)),)
    )
    issue = next(i for i in check_batch(_manifest(), batch) if i.code == "field_too_long")
    assert issue.field == "entity_moid"
    assert issue.severity == "warning"


def test_empty_entity_moid_is_reported() -> None:
    batch = CollectionBatch(metrics=(_sample(entity_moid=""),))
    assert "empty_entity_moid" in _codes(check_batch(_manifest(), batch), "warning")


def test_duplicate_metric_dedup_key_is_reported() -> None:
    """DB は (vcenter_id, sampled_at, entity_moid, metric_key) で一意。片方が黙って消える。"""
    batch = CollectionBatch(metrics=(_sample(value=1.0), _sample(value=2.0)))
    issues = [i for i in check_batch(_manifest(), batch) if i.code == "duplicate_dedup_key"]
    assert len(issues) == 1
    assert issues[0].index == 1


def test_samples_differing_only_by_timestamp_are_not_duplicates() -> None:
    batch = CollectionBatch(
        metrics=(
            _sample(sampled_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            _sample(sampled_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
        )
    )
    assert _codes(check_batch(_manifest(), batch), "warning") == []


def test_duplicate_vmware_key_is_reported() -> None:
    manifest = _manifest(data_kinds=frozenset({"event"}), metric_definitions=())
    batch = CollectionBatch(events=(_event(), _event(message="again")))
    assert "duplicate_dedup_key" in _codes(check_batch(manifest, batch), "warning")


def test_vmware_key_outside_int32_is_reported() -> None:
    """Integer 列なので PostgreSQL では失敗する。SQLite では通ってしまうため気づきにくい。"""
    manifest = _manifest(data_kinds=frozenset({"event"}), metric_definitions=())
    batch = CollectionBatch(events=(_event(vmware_key=limits.VMWARE_KEY_MAX + 1),))
    assert "vmware_key_out_of_int32_range" in _codes(check_batch(manifest, batch), "warning")


def test_vmware_key_at_the_boundary_is_accepted() -> None:
    manifest = _manifest(data_kinds=frozenset({"event"}), metric_definitions=())
    for key in (limits.VMWARE_KEY_MIN, limits.VMWARE_KEY_MAX):
        batch = CollectionBatch(events=(_event(vmware_key=key),))
        assert _codes(check_batch(manifest, batch), "warning") == []


def test_error_messages_never_contain_vcenter_data() -> None:
    """error だけがワーカー越しに親へ渡りうるため、データを含めてはならない。"""
    manifest = _manifest(data_kinds=frozenset({"event"}), metric_definitions=())
    batch = CollectionBatch(
        events=(
            _event(
                occurred_at=datetime(2026, 1, 1),
                message="secret-message-body",
                entity_name="secret-host-name",
                user_name="secret-user",
            ),
        )
    )
    with pytest.raises(BatchValidationError) as excinfo:
        validate_batch(manifest, batch)
    text = str(excinfo.value)
    assert "secret-message-body" not in text
    assert "secret-host-name" not in text
    assert "secret-user" not in text


# --- raise_for_issues: アプリが使う 1 回走査の経路 -------------------------


def test_raise_for_issues_matches_validate_batch() -> None:
    """アプリはバッチを 1 回だけ走査してから送出する。判定は同じでなければならない。"""
    batch = CollectionBatch(metrics=(_sample(metric_key="other.key"),))
    issues = check_batch(_manifest(), batch)
    with pytest.raises(BatchValidationError) as from_issues:
        raise_for_issues(issues)
    with pytest.raises(BatchValidationError) as from_batch:
        validate_batch(_manifest(), batch)
    assert str(from_issues.value) == str(from_batch.value)


def test_raise_for_issues_ignores_warnings() -> None:
    batch = CollectionBatch(metrics=(_sample(entity_moid=""),))
    issues = check_batch(_manifest(), batch)
    assert [i.severity for i in issues] == ["warning"]
    raise_for_issues(issues)  # 送出しない


def test_raise_for_issues_accepts_an_empty_result() -> None:
    raise_for_issues(())
