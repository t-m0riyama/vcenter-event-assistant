"""Linux subreaper for one isolated plugin session or installation job."""

from __future__ import annotations

import contextlib
import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType

_PR_SET_CHILD_SUBREAPER = 36


class _Stopped(Exception):
    pass


def _stop(_signal: int, _frame: FrameType | None) -> None:
    raise _Stopped


def _reap_children(children: Path) -> None:
    # Orphaned descendants are reparented to this process even when they
    # have left the original child process group.
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid:
            continue
        for descendant in children.read_text().split():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(descendant), signal.SIGKILL)
        time.sleep(0.01)


def main() -> int:
    args = sys.argv[1:]
    ready_fd = None
    if args and args[0].startswith("--ready-fd="):
        ready_fd = int(args.pop(0).split("=", 1)[1])
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    if not children.is_file():
        raise RuntimeError("plugin supervision requires Linux procfs children support")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "could not enable plugin child supervision")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    child = None
    try:
        child = subprocess.Popen(args, start_new_session=True)
        if ready_fd is not None:
            os.write(ready_fd, b"1")
            os.close(ready_fd)
        status = child.wait()
        return status if status >= 0 else 128 - status
    except _Stopped:
        return 128 + signal.SIGTERM
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if child is not None and child.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
        _reap_children(children)


if __name__ == "__main__":
    raise SystemExit(main())
