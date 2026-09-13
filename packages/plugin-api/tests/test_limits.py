"""列長の定数と安定キー生成。"""

from __future__ import annotations

from vcenter_event_assistant_plugin_api import limits


def test_truncate_keeps_short_values_as_is() -> None:
    assert limits.truncate("abc", 10) == "abc"


def test_truncate_marks_that_it_cut() -> None:
    result = limits.truncate("abcdefghij", 5)
    assert len(result) == 5
    assert result.endswith("…")


def test_truncate_handles_limits_shorter_than_the_ellipsis() -> None:
    assert limits.truncate("abcdef", 1) == "a"


def test_truncate_with_a_zero_limit_is_empty() -> None:
    assert limits.truncate("abc", 0) == ""


def test_stable_ints_are_deterministic_across_calls() -> None:
    assert limits.stable_int63("vc-1", "host-1") == limits.stable_int63("vc-1", "host-1")
    assert limits.stable_int31("vc-1", "host-1") == limits.stable_int31("vc-1", "host-1")


def test_stable_ints_are_positive_and_fit_their_width() -> None:
    for parts in (("a",), ("a", "b"), (1, None, "x")):
        assert 0 <= limits.stable_int63(*parts) <= 2**63 - 1
        assert 0 <= limits.stable_int31(*parts) <= limits.VMWARE_KEY_MAX


def test_different_inputs_give_different_keys() -> None:
    assert limits.stable_int63("a", "b") != limits.stable_int63("b", "a")
    # 区切り文字が効いていること（"ab" と ("a","b") が衝突しない）。
    assert limits.stable_int63("ab") != limits.stable_int63("a", "b")


def test_vmware_key_bounds_match_a_signed_32_bit_column() -> None:
    assert limits.VMWARE_KEY_MIN == -(2**31)
    assert limits.VMWARE_KEY_MAX == 2**31 - 1


def test_metric_and_event_entity_type_limits_differ() -> None:
    """取り違えやすいので明示的に固定する。"""
    assert limits.MAX_METRIC_ENTITY_TYPE == 128
    assert limits.MAX_EVENT_ENTITY_TYPE == 256
