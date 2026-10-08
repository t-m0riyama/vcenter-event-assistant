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

既存サーバーで認証が有効なときは、ログインに使う admin の資格情報が必要になる。
``E2E_USERNAME`` / ``E2E_PASSWORD`` を環境変数で渡すか、``--username`` を指定してパスワードを対話入力する
（どちらも無ければユーザー名とパスワードを対話入力する）。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
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


def _auth_enabled(base_url: str) -> bool:
    """既存サーバーで認証が有効か（``/api/auth/me`` が 401 なら有効）。判定できなければ有効とみなす。"""
    try:
        with urllib.request.urlopen(f"{base_url}/api/auth/me", timeout=10) as resp:
            return bool(json.load(resp).get("auth_enabled", True))
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            print(f"警告: {base_url}/api/auth/me が {exc.code} を返しました。", file=sys.stderr)
        return True
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"{base_url} に接続できません: {exc}", file=sys.stderr)
        sys.exit(1)


def _login_env(base_url: str, username: str | None) -> dict[str, str]:
    """認証が有効な既存サーバー向けに、Playwright の setup が使う資格情報を用意する。"""
    if not _auth_enabled(base_url):
        return {}
    user = username or os.environ.get("E2E_USERNAME") or input("ログインするユーザー名（admin）: ").strip()
    password = os.environ.get("E2E_PASSWORD") or getpass.getpass(f"{user} のパスワード: ")
    if not user or not password:
        print("ユーザー名とパスワードが必要です。", file=sys.stderr)
        sys.exit(1)
    return {"E2E_USERNAME": user, "E2E_PASSWORD": password}


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
    parser.add_argument(
        "--username",
        type=str,
        default=None,
        help="既存サーバーで認証が有効なときにログインするユーザー（未指定時は E2E_USERNAME か対話入力）。",
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
        base_url = args.base_url.rstrip("/")
        env["E2E_BASE_URL"] = base_url
    else:
        base_url = f"http://127.0.0.1:{args.port}"
        env["E2E_PORT"] = str(args.port)
    env.update(_login_env(base_url, args.username))
    _run(play_cmd, cwd=frontend, extra_env=env)


if __name__ == "__main__":
    main()
