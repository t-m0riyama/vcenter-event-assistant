"""``ensure_aware`` と ``to_utc`` の違いを固定する。

取り違えると既存イベントの時刻がずれる。``ensure_aware`` は naive に付与するだけで
aware は触らない。``to_utc`` は aware も UTC へ変換する。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vcenter_event_assistant_plugin_api.timeutils import (
    ensure_aware,
    is_aware,
    now_utc,
    to_utc,
)

JST = timezone(timedelta(hours=9))


def test_now_utc_is_aware() -> None:
    assert is_aware(now_utc())
    assert now_utc().tzinfo is timezone.utc


def test_is_aware_matches_the_app_condition() -> None:
    assert is_aware(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert not is_aware(datetime(2026, 1, 1))


def test_ensure_aware_only_attaches_to_naive_values() -> None:
    naive = datetime(2026, 1, 1, 12, 0)
    assert ensure_aware(naive) == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_ensure_aware_leaves_aware_values_untouched() -> None:
    """ここが `to_utc` との分かれ目。壁時計の値を変えない。"""
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=JST)
    assert ensure_aware(aware) is aware
    assert ensure_aware(aware).hour == 12


def test_ensure_aware_can_assume_another_zone() -> None:
    naive = datetime(2026, 1, 1, 12, 0)
    assert ensure_aware(naive, assume=JST).utcoffset() == timedelta(hours=9)


def test_to_utc_converts_aware_values() -> None:
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=JST)
    converted = to_utc(aware)
    assert converted.tzinfo is timezone.utc
    assert converted.hour == 3


def test_to_utc_treats_naive_as_utc() -> None:
    assert to_utc(datetime(2026, 1, 1, 12, 0)).hour == 12
