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
import os
import re
import sys
from pathlib import Path

from vcenter_event_assistant.plugins.subprocess_env import url_has_credentials
from vcenter_event_assistant.settings import Settings

logger = logging.getLogger(__name__)

_PR_SET_DUMPABLE = 4

# 親プロセスの環境変数に残っていると危ない名前（値は見ない）。Settings は大文字と小文字を
# 区別せずに読むので、``database_url`` などの小文字の名前も対象にする。
_SECRET_ENV_NAME_RE = re.compile(
    r"VEA_SECRET_KEY|DATABASE_URL|[A-Z0-9_]*(?:PASSWORD|API_KEY|SECRET|TOKEN)",
    re.IGNORECASE,
)
# 値に資格情報（``user:pass@``）を含むときだけ危ない URL の変数。``HTTP_PROXY``・
# ``SEARCH_HTTP_PROXY``・``VEA_PLUGIN_INDEX_URL``・``UV_DEFAULT_INDEX``・``LLM_CHAT_BASE_URL``・
# ``LANGSMITH_ENDPOINT`` など。名前を 1 つずつ並べると漏れるので、名前の形で判定する。
# 関係のない変数を拾っても、出るのは警告だけ。
_CREDENTIAL_URL_ENV_NAME_RE = re.compile(r".*(?:PROXY|_URL|_URI|_ENDPOINT|_INDEX)", re.IGNORECASE)


def _secret_env_names(environ: bytes) -> list[str]:
    """``/proc/<pid>/environ`` の中身から、秘密を持つ変数の名前を返す（値は返さない）。"""
    names: set[str] = set()
    for entry in environ.decode("utf-8", errors="replace").split("\0"):
        name, sep, value = entry.partition("=")
        if not sep:
            continue
        if _SECRET_ENV_NAME_RE.fullmatch(name) or (
            _CREDENTIAL_URL_ENV_NAME_RE.fullmatch(name) and url_has_credentials(value)
        ):
            names.add(name)
    return sorted(names)


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


def warn_if_parent_keeps_secrets(*, proc_root: Path = Path("/proc")) -> bool:
    """親プロセスが同じ UID で秘密の環境変数を持ったまま残っていれば WARNING を出す。

    ``uv run`` や同じユーザーで動くプロセス管理ツールから起動すると、親は起動時の環境変数を
    持ったまま残る。``harden_process`` で守れるのはアプリのプロセスだけなので、プラグインの
    ワーカーは ``/proc/<親の pid>/environ`` から読める（PR #273 の Codex レビューの指摘）。
    起動方法の問題なので、止めずに知らせる。警告したら True。
    """
    if not sys.platform.startswith("linux"):
        return False
    ppid = os.getppid()
    parent = proc_root / str(ppid)
    try:
        status = (parent / "status").read_text(encoding="utf-8", errors="replace")
        environ = (parent / "environ").read_bytes()
    except OSError:
        return False
    uid_line = next((line for line in status.splitlines() if line.startswith("Uid:")), "")
    uids = uid_line.split()[1:]
    if not uids or int(uids[0]) != os.getuid():
        return False
    names = _secret_env_names(environ)
    if not names:
        return False
    name_line = next((line for line in status.splitlines() if line.startswith("Name:")), "Name:\t?")
    logger.warning(
        "the parent process (pid=%s, %s) runs as the same user and keeps secret environment "
        "variables (%s); plugin workers can read them from /proc/%s/environ. "
        "In production, start the app so that it replaces the launcher, for example "
        "'exec .venv/bin/vcenter-event-assistant' instead of 'uv run' (without exec, an "
        "interactive shell stays as the parent). A process manager that keeps running must "
        "run as a different user (e.g. systemd as root) or must not hold these variables; "
        "exec does not help there.",
        ppid,
        name_line.split(None, 1)[-1].strip(),
        ", ".join(names),
        ppid,
    )
    return True
