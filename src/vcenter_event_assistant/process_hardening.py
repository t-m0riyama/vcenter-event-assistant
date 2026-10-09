"""本体のプロセスを、同じ UID で動く子プロセス（プラグイン）から守る。

プラグインのワーカーは本体と同じ UID で動くので、そのままでは ``/proc/<本体の pid>/environ``
（``VEA_SECRET_KEY`` などの環境変数）や ``/proc/<pid>/mem`` を読める。Linux では
``prctl(PR_SET_DUMPABLE, 0)`` でこれを防ぐ（監査 M-1）。子プロセスは execve で dumpable に
戻るので、ワーカー自身の動作には影響しない。
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import sys

from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

_PR_SET_DUMPABLE = 4


def harden_process(settings: Settings) -> bool:
    """有効で Linux なら本体のプロセスを dumpable でなくする。適用したら True。"""
    if not settings.process_non_dumpable or not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        if libc.prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_DUMPABLE) failed")
    except (OSError, AttributeError):
        logger.warning(
            "could not make the process non-dumpable; plugin workers may read its environment",
            exc_info=True,
        )
        return False
    return True
