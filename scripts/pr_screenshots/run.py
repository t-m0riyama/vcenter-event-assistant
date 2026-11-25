"""PR のレビュー用に、画面の場面ごとのスクリーンショットを明暗の両テーマで撮る。

``docs/images`` を更新する ``scripts/capture_ui_screenshots.py`` とは別の道具で、リポジトリには
書き込まない。撮るたびに一時の SQLite でモックモードのサーバーを立て、場面のデモデータを入れ、
Playwright（Chromium）で撮ってからサーバーを止める。外部のサービスには接続しない。

場面は ``scenarios/<名前>.py``（``seed(client, db_path)`` でデモデータを入れる）と
``scenarios/<名前>.mjs``（``shots(page, ctx)`` で撮る）の組で足す。

使い方::

    uv run python scripts/pr_screenshots/run.py diagnostics-settings --out /tmp/shots
    uv run python scripts/pr_screenshots/run.py diagnostics-settings --out /tmp/shots --build
    uv run python scripts/pr_screenshots/run.py --list

前提: ``frontend`` で ``npm install`` と ``npx playwright install chromium`` を済ませておく。
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType

import httpx

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parent.parent
SCENARIOS = HERE / "scenarios"
# デモ専用のサーバーにだけ使う資格情報と秘密鍵（撮影のたびに捨てる一時の DB に入る）。
ADMIN_USERNAME = "demo-admin"
ADMIN_PASSWORD = "demo-admin-password-01"
DEMO_SECRET_KEY = "pr-screenshots-demo-secret"


def scenario_names() -> list[str]:
    return sorted(path.stem.replace("_", "-") for path in SCENARIOS.glob("*.mjs"))


def load_seed(name: str) -> ModuleType | None:
    path = SCENARIOS / f"{name.replace('-', '_')}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"pr_screenshot_scenario_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def server_env(db_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "MOCK_MODE": "1",
        "SCHEDULER_ENABLED": "false",
        "VEA_AUTH_ENABLED": "true",
        "VEA_DIAGNOSTICS_ENABLED": "true",
        "VEA_SECRET_KEY": DEMO_SECRET_KEY,
        "VEA_BOOTSTRAP_ADMIN_USERNAME": ADMIN_USERNAME,
        "VEA_BOOTSTRAP_ADMIN_PASSWORD": ADMIN_PASSWORD,
    }


def port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for_health(base: str, server: subprocess.Popen[bytes], log: Path) -> None:
    for _ in range(60):
        if server.poll() is not None:
            raise RuntimeError(f"サーバーが起動しませんでした。ログ: {log}")
        try:
            if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError(f"サーバーが 60 秒たっても応答しません。ログ: {log}")


def login(base: str) -> httpx.Client:
    client = httpx.Client(base_url=base, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=60)
    client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}).raise_for_status()
    return client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", nargs="?", help="撮る場面（--list で一覧）")
    parser.add_argument("--out", type=Path, help="PNG を書き出すディレクトリ")
    parser.add_argument("--port", type=int, default=9331, help="一時のサーバーのポート（既定 9331）")
    parser.add_argument("--build", action="store_true", help="撮る前に frontend で npm run build する")
    parser.add_argument("--list", action="store_true", help="場面の一覧を表示して終わる")
    args = parser.parse_args(argv)

    if args.list:
        print("\n".join(scenario_names()))
        return 0
    if args.scenario not in scenario_names() or args.out is None:
        parser.error(f"場面（{', '.join(scenario_names())}）と --out を指定してください。")
    if port_in_use(args.port):
        print(f"ポート {args.port} は使用中です。--port で別のポートを指定してください。", file=sys.stderr)
        return 1
    if args.build:
        subprocess.run(["npm", "run", "build"], cwd=REPOSITORY_ROOT / "frontend", check=True)
    args.out.mkdir(parents=True, exist_ok=True)

    base = f"http://127.0.0.1:{args.port}"
    with tempfile.TemporaryDirectory(prefix="vea-pr-shots-") as work:
        db_path, log = Path(work) / "demo.db", Path(work) / "server.log"
        with log.open("wb") as log_file:
            server = subprocess.Popen(
                [
                    "uv", "run", "--no-sync", "uvicorn", "vcenter_event_assistant.main:create_app",
                    "--factory", "--host", "127.0.0.1", "--port", str(args.port),
                ],
                cwd=REPOSITORY_ROOT, env=server_env(db_path), stdout=log_file, stderr=subprocess.STDOUT,
            )
            try:
                wait_for_health(base, server, log)
                seed = load_seed(args.scenario)
                if seed is not None:
                    client = login(base)
                    try:
                        seed.seed(client, db_path)
                    finally:
                        client.close()
                result = subprocess.run(
                    ["node", str(HERE / "shoot.mjs"), base, str(args.out.resolve()), args.scenario],
                    cwd=REPOSITORY_ROOT / "frontend",
                    env={**os.environ, "VEA_DEMO_USERNAME": ADMIN_USERNAME, "VEA_DEMO_PASSWORD": ADMIN_PASSWORD},
                    check=False,
                )
            except Exception:
                print(log.read_text(encoding="utf-8", errors="replace")[-3000:], file=sys.stderr)
                raise
            finally:
                server.terminate()
                server.wait(timeout=30)
    if result.returncode == 0:
        print(f"{args.out} に書き出しました。")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
