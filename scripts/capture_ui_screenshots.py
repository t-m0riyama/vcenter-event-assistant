# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
UI スクリーンショットを `docs/images/` に出力する（Playwright）。

使い方:
  uv run scripts/capture_ui_screenshots.py
  uv run scripts/capture_ui_screenshots.py --existing
  uv run scripts/capture_ui_screenshots.py --existing --port 9000
  uv run scripts/capture_ui_screenshots.py --existing --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> None:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="docs/images 向け UI スクリーンショットを Playwright で取得する",
    )
    parser.add_argument(
        "--existing",
        "-e",
        action="store_true",
        help="既に起動している API に向ける（フロントの build を省略）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="--existing 時の接続先ポート（既定: 8000）",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        metavar="URL",
        help="接続先をまとめて指定（例: http://127.0.0.1:8000）。指定時は --port より優先",
    )
    args = parser.parse_args()

    root = _repo_root()
    frontend = root / "frontend"
    if not (frontend / "package.json").is_file():
        print("frontend/package.json が見つかりません。リポジトリルートで実行してください。", file=sys.stderr)
        sys.exit(1)

    spec = "e2e/screenshots.spec.ts"
    play_cmd = ["npx", "playwright", "test", spec]

    if args.existing:
        env: dict[str, str] = {"PLAYWRIGHT_USE_EXISTING_SERVER": "1"}
        if args.base_url:
            env["E2E_BASE_URL"] = args.base_url.rstrip("/")
        else:
            env["E2E_PORT"] = str(args.port)
        _run(play_cmd, cwd=frontend, extra_env=env)
        return

    _run(["npm", "run", "build"], cwd=frontend)
    _run(play_cmd, cwd=frontend)


if __name__ == "__main__":
    main()
