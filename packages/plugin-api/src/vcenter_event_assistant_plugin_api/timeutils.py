"""Timezone-aware datetime helpers.

アプリはバッチ内の naive な datetime を拒否する（``sampled_at`` / ``occurred_at``）。
拒否は 1 件でもバッチ全体に及ぶため、``datetime.now()`` を ``timezone.utc`` なしで
書いてしまうのは最も高価な取り違えである。
"""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo


def now_utc() -> datetime:
    """timezone-aware な現在時刻（UTC）。``datetime.now(timezone.utc)`` と同じ。"""
    return datetime.now(timezone.utc)


def is_aware(value: datetime) -> bool:
    """アプリの検証と同じ条件で timezone-aware かを判定する。"""
    return value.tzinfo is not None


def ensure_aware(value: datetime, *, assume: tzinfo = timezone.utc) -> datetime:
    """naive なら ``assume`` を**付与する**。aware なら**そのまま返す**。

    :func:`to_utc` と違い、aware な値のタイムゾーンを変換しない。イベントの元データが
    ローカル時刻で来る場合に、UTC へ読み替えてしまわないための区別である。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=assume)
    return value


def to_utc(value: datetime) -> datetime:
    """UTC に**変換する**。naive は UTC として解釈する。

    :func:`ensure_aware` と使い分けること。aware な値も UTC へ変換する点が異なる。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
