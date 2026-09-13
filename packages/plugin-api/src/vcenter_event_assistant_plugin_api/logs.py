"""Logging conventions for plugins.

**ハンドラ・レベル・``basicConfig`` を設定してはならない。** それはホスト（コレクタ
ワーカー）の責務である。ここが提供するのは名前空間の規約だけで、ワーカーが
``VEA_COLLECTOR_WORKER_LOG_LEVEL`` でこの配下だけを切り替えられるようにするためにある。

ワーカーの stdout は JSON Lines プロトコル専用なので、``print`` ではなく logging を
使うこと（``print`` は起動時に stderr へ振り替えられるためプロトコルは壊れないが、
レベルもタイムスタンプも付かない）。
"""

from __future__ import annotations

import logging

#: 外部プラグインのロガーが属する名前空間。
PLUGIN_LOGGER_NAMESPACE = "vcenter_event_assistant.plugins.external"


def get_plugin_logger(plugin_id: str, *, suffix: str | None = None) -> logging.Logger:
    """``PLUGIN_LOGGER_NAMESPACE`` 配下のロガーを返す。

    Args:
        plugin_id: ``CollectorManifest.id``。
        suffix: 同一プラグイン内で出力を分けたい場合の追加要素。
    """
    name = f"{PLUGIN_LOGGER_NAMESPACE}.{plugin_id}"
    if suffix:
        name = f"{name}.{suffix}"
    return logging.getLogger(name)
