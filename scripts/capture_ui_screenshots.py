# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
UI スクリーンショットを `docs/images/` に出力する（Playwright）。

既定は **既に起動している** アプリ（例: ``http://127.0.0.1:8000``）に接続する。
メモリ DB ＋ ``SCREENSHOT_E2E_SEED`` 付きで Playwright がサーバーを立てる場合は
``--spawn-server`` を使う（主に CI／自動検証向け）。

使い方:
  uv run scripts/capture_ui_screenshots.py
  uv run scripts/capture_ui_screenshots.py --build
  uv run scripts/capture_ui_screenshots.py --port 9000
  uv run scripts/capture_ui_screenshots.py --base-url http://127.0.0.1:8000
  uv run scripts/capture_ui_screenshots.py --spawn-server
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


def _screenshot_playwright_env() -> dict[str, str]:
    """ドキュメント用 `screenshots.spec.ts` 実行用（testIgnore 解除・`docs/images` への書き込み許可）。"""
    return {
        "E2E_RUN_SCREENSHOTS_SPEC": "1",
        "WRITE_DOC_SCREENSHOTS_TO_REPO": "1",
    }


def _spawn_server_env() -> dict[str, str]:
    """Playwright が webServer で API を起動するとき、ドキュメント用 DB シードを有効にする。"""
    return {**_screenshot_playwright_env(), "SCREENSHOT_E2E_SEED": "1"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="docs/images 向け UI スクリーンショットを Playwright で取得する",
    )
    parser.add_argument(
        "--spawn-server",
        action="store_true",
        help=(
            "Playwright の webServer で uvicorn を起動する（メモリ DB・SCREENSHOT_E2E_SEED）。"
            " 未指定時は既定で既存のローカルインスタンスに接続する。"
        ),
    )
    parser.add_argument(
        "--build",
        "-b",
        action="store_true",
        help="実行前に frontend で npm run build する（既存サーバー向けでも可）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="既存サーバー接続先ポート（既定: 8000）。--base-url 指定時は無視。",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        metavar="URL",
        help="接続先をまとめて指定（例: http://127.0.0.1:8000）。指定時は --port より優先。",
    )
    args = parser.parse_args()

    root = _repo_root()
    frontend = root / "frontend"
    if not (frontend / "package.json").is_file():
        print("frontend/package.json が見つかりません。リポジトリルートで実行してください。", file=sys.stderr)
        sys.exit(1)

    spec = "e2e/screenshots.spec.ts"
    play_cmd = ["npx", "playwright", "test", spec]

    if args.build:
        _run(["npm", "run", "build"], cwd=frontend)

    if args.spawn_server:
        _run(play_cmd, cwd=frontend, extra_env=_spawn_server_env())
        return

    env: dict[str, str] = {
        "PLAYWRIGHT_USE_EXISTING_SERVER": "1",
        **_screenshot_playwright_env(),
    }
    if args.base_url:
        env["E2E_BASE_URL"] = args.base_url.rstrip("/")
    else:
        env["E2E_PORT"] = str(args.port)
    _run(play_cmd, cwd=frontend, extra_env=env)


if __name__ == "__main__":
    main()
