"""Datetime helpers for API query parameters."""

from __future__ import annotations

from vcenter_event_assistant_plugin_api.timeutils import to_utc as to_utc

# 実装は plugin-api 側にある（`timeutils.to_utc`）。プラグイン作者もアプリと同じ
# 正規化を使えるようにするための一元化で、ここは既存の import 経路を保つための再公開。
#
# 注意: naive を UTC 扱いし、aware は UTC へ**変換する**。naive に付与するだけの
# `ensure_aware` とは別物である。

__all__ = ["to_utc"]
