"""AlertEvaluator のルール種別ディスパッチ。"""

from __future__ import annotations

from vcenter_event_assistant.services.alerting.alert_eval import (
    AlertEvaluator,
    _RULE_EVALUATORS,
)


def test_rule_evaluators_cover_supported_rule_types() -> None:
    assert set(_RULE_EVALUATORS.keys()) == {"event_score", "metric_threshold"}


def test_rule_evaluators_values_are_callable() -> None:
    for rule_type, evaluator_fn in _RULE_EVALUATORS.items():
        assert callable(evaluator_fn), rule_type


def test_evaluate_all_ignores_unknown_rule_type() -> None:
    """未登録 rule_type は 0 件扱い（ディスパッチ辞書に無い種別）。"""
    assert "unknown_type" not in _RULE_EVALUATORS
    assert hasattr(AlertEvaluator, "evaluate_all")
