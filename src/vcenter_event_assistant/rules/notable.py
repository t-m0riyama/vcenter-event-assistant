"""ルールベースの notable イベントスコアリング（純関数）。

イベント種別・重大度・メッセージから 0..100 のスコアとタグを算出する。
"""

from __future__ import annotations

from dataclasses import dataclass

HIGH_ATTENTION_TYPES: frozenset[str] = frozenset(
    {
        "VmFailedToPowerOnEvent",
        "VmFailedToStandbyGuestEvent",
        "VmFailedToSuspendEvent",
        "HostConnectionLostEvent",
        "HostNotRespondingEvent",
        "DatastoreRemovedOnHostEvent",
    }
)

SEVERITY_WEIGHT: dict[str, int] = {
    "error": 40,
    "warning": 20,
    "info": 0,
    "user": 0,
}


@dataclass(frozen=True, slots=True)
class NotableResult:
    """notable 判定のスコアと付与タグ。"""

    score: int
    tags: list[str]


def _matches_pattern(event_type: str, pattern: str) -> bool:
    if pattern.endswith("*"):
        return event_type.startswith(pattern[:-1])
    return event_type == pattern


def score_event(
    *,
    event_type: str,
    severity: str | None,
    message: str,
) -> NotableResult:
    """イベントフィールドから notable スコアとタグを算出する。"""
    tags: list[str] = []
    score = 0

    sev = (severity or "").lower()
    if sev in SEVERITY_WEIGHT:
        w = SEVERITY_WEIGHT[sev]
        score += w
        if w:
            tags.append(f"severity:{sev}")

    for p in HIGH_ATTENTION_TYPES:
        if _matches_pattern(event_type, p):
            score += 35
            tags.append("high_risk_type")
            break

    lowered = message.lower()
    if any(x in lowered for x in ("fail", "error", "lost", "timeout", "corrupt")):
        score += 10
        tags.append("keyword_alert")

    # dedupe tags
    seen: set[str] = set()
    uniq_tags: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq_tags.append(t)

    return NotableResult(score=min(score, 100), tags=uniq_tags)


def clamp_notable_total(base_score: int, score_delta: int) -> int:
    """加算 delta を適用し 0..100 にクランプする（保存 ``notable_score`` と同義）。"""
    return max(0, min(100, base_score + score_delta))


def final_notable_score(
    *,
    event_type: str,
    severity: str | None,
    message: str,
    score_delta: int = 0,
) -> int:
    """``score_event`` の基底スコアに種別 delta を加え、0..100 にクランプする。"""
    base = score_event(event_type=event_type, severity=severity, message=message).score
    return clamp_notable_total(base, score_delta)


def flag_metric_spike(
    *,
    metric_key: str,
    value: float,
    warn_threshold: float = 85.0,
    crit_threshold: float = 95.0,
) -> NotableResult:
    """閾値超過時にメトリクスサンプルを notable として分類する。"""
    if value >= crit_threshold:
        return NotableResult(score=90, tags=[f"metric:{metric_key}", "threshold:critical"])
    if value >= warn_threshold:
        return NotableResult(score=55, tags=[f"metric:{metric_key}", "threshold:warning"])
    return NotableResult(score=0, tags=[])
