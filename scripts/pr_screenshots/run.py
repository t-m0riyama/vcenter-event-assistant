"""PR のレビュー用に、画面の場面ごとのスクリーンショットを明暗の両テーマで撮る。

``docs/images`` を更新する ``scripts/capture_ui_screenshots.py`` とは別の道具で、リポジトリには
書き込まない。撮るたびに一時の SQLite でモックモードのサーバーを立て、場面のデモデータを入れ、
Playwright（Chromium）で撮ってからサーバーを止める。外部のサービスには接続しない。

場面は ``scenarios/<名前>.py`` と ``scenarios/<名前>.mjs``（``shots(page, ctx)`` で撮る）の組で足す。
``.py`` には、サーバーの起動前に足す環境変数 ``SERVER_ENV``（例: 起動時のシード
``SCREENSHOT_E2E_SEED``）と、起動後に API でデモデータを入れる ``seed(client, db_path)`` の、
どちらか一方または両方を置く。

使い方::

    uv run python scripts/pr_screenshots/run.py diagnostics-settings --out /tmp/shots
    uv run python scripts/pr_screenshots/run.py diagnostics-settings --out /tmp/shots --build
    uv run python scripts/pr_screenshots/run.py --list
    uv run python scripts/pr_screenshots/run.py config-diffs --out /tmp/shots --publish config-diffs-ui

``--publish <名前>`` は、撮った PNG だけを入れた親の無いコミットを作り、``origin`` の
``screenshots/<名前>`` ブランチに push する（作業ツリーと今のブランチには触れない）。PR の説明に
貼る画像の Markdown を出す。同じ名前のブランチが既にあるときと、出力先が空でないときは、撮らずに止まる。

前提: ``frontend`` で ``npm install`` と ``npx playwright install chromium`` を済ませておく。
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType
from urllib.parse import quote

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


def server_env(db_path: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
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
        **(extra or {}),
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


def github_slug(remote_url: str) -> str:
    """``origin`` の URL から ``owner/repo`` を取り出す（https と ssh の両方の形）。"""
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", remote_url)
    if match is None:
        raise ValueError(f"GitHub のリポジトリの URL ではありません: {remote_url}")
    return match.group(1)


class PublishError(Exception):
    """公開できない（利用者に短い案内で返す）。"""


def _git(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=False, capture_output=True, text=True)


def prepare_publish(name: str, out: Path, cwd: Path = REPOSITORY_ROOT) -> str:
    """撮る前に公開できるかを確かめ、``owner/repo`` を返す。

    名前の形、``origin`` が GitHub か、同じ名前のブランチが無いか、出力先が空かを確かめる。
    出力先に前の PNG が残っていると、それも公開してしまうため。
    """
    branch = f"refs/heads/screenshots/{name}"
    if _git("check-ref-format", branch, cwd=cwd).returncode != 0:
        raise PublishError(f"ブランチの名前に使えません: {name}")
    remote = _git("remote", "get-url", "origin", cwd=cwd)
    if remote.returncode != 0:
        raise PublishError("origin が設定されていません。")
    try:
        slug = github_slug(remote.stdout.strip())
    except ValueError as exc:
        raise PublishError(str(exc)) from exc
    exists = _git("ls-remote", "--exit-code", "origin", branch, cwd=cwd)
    if exists.returncode == 0:
        raise PublishError(f"origin に {branch} が既にあります。別の名前を指定してください。")
    if exists.returncode != 2:
        raise PublishError(f"origin を確かめられませんでした: {exists.stderr.strip()}")
    if out.exists() and not out.is_dir():
        raise PublishError(f"{out} はディレクトリではありません。")
    if out.exists() and any(out.iterdir()):
        raise PublishError(f"{out} が空ではありません。--publish では空の出力先を指定してください。")
    return slug


def screenshot_commit(out: Path, cwd: Path = REPOSITORY_ROOT) -> tuple[str, list[str]]:
    """``out`` の PNG だけを入れた親の無いコミットを作り、そのハッシュとファイル名を返す。

    一時の index を使うので、作業ツリー、今の index、今のブランチは変わらない。
    """
    names = sorted(path.name for path in out.glob("*.png"))
    if not names:
        raise PublishError(f"{out} に PNG がありません。")

    def git(*args: str, env: dict[str, str] | None = None) -> str:
        result = _git(*args, cwd=cwd, env=env)
        if result.returncode != 0:
            raise PublishError(f"git {args[0]} に失敗しました: {result.stderr.strip()}")
        return result.stdout.strip()

    with tempfile.TemporaryDirectory(prefix="vea-pr-shots-index-") as work:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(work) / "index")}
        for name in names:
            blob = git("hash-object", "-w", str(out / name))
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{name}", env=env)
        tree = git("write-tree", env=env)
    commit = git("commit-tree", tree, "-m", f"screenshots: {out.name}")
    return commit, names


def _pair_key(name: str) -> tuple[str, int]:
    """``light-<名前>.png`` と ``dark-<名前>.png`` を、場面ごとに明るい側を先にして並べる。"""
    for order, theme in enumerate(("light-", "dark-")):
        if name.startswith(theme):
            return name.removeprefix(theme), order
    return name, 2


def image_markdown(slug: str, commit: str, names: list[str]) -> str:
    """PR の説明に貼る画像の Markdown（場面ごとに明暗の組で並べる）。"""
    base = f"https://raw.githubusercontent.com/{slug}/{commit}"
    return "\n".join(
        f"![{name.removesuffix('.png')}]({base}/{quote(name)})" for name in sorted(names, key=_pair_key)
    )


def publish(out: Path, name: str, slug: str, cwd: Path = REPOSITORY_ROOT) -> str:
    """PNG を ``screenshots/<name>`` に push し、画像の Markdown を返す。

    ``+`` を付けずに push するので、同じ名前のブランチが後からできていても上書きしない。
    refspec は 1 つの引数で渡す（シェルを通さないので、変数の修飾子などで崩れない）。
    """
    commit, names = screenshot_commit(out, cwd=cwd)
    pushed = _git("push", "origin", f"{commit}:refs/heads/screenshots/{name}", cwd=cwd)
    if pushed.returncode != 0:
        raise PublishError(f"push に失敗しました: {pushed.stderr.strip()}")
    return image_markdown(slug, commit, names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", nargs="?", help="撮る場面（--list で一覧）")
    parser.add_argument("--out", type=Path, help="PNG を書き出すディレクトリ")
    parser.add_argument("--port", type=int, default=9331, help="一時のサーバーのポート（既定 9331）")
    parser.add_argument("--build", action="store_true", help="撮る前に frontend で npm run build する")
    parser.add_argument("--list", action="store_true", help="場面の一覧を表示して終わる")
    parser.add_argument(
        "--publish", metavar="NAME", help="撮った PNG を origin の screenshots/NAME ブランチに push し、画像の Markdown を出す",
    )
    args = parser.parse_args(argv)

    if args.list:
        print("\n".join(scenario_names()))
        return 0
    if args.scenario not in scenario_names() or args.out is None:
        parser.error(f"場面（{', '.join(scenario_names())}）と --out を指定してください。")
    args.out = args.out.resolve()
    slug = None
    if args.publish:
        try:
            slug = prepare_publish(args.publish, args.out)
        except PublishError as exc:
            print(exc, file=sys.stderr)
            return 1
    if port_in_use(args.port):
        print(f"ポート {args.port} は使用中です。--port で別のポートを指定してください。", file=sys.stderr)
        return 1
    if args.build:
        subprocess.run(["npm", "run", "build"], cwd=REPOSITORY_ROOT / "frontend", check=True)
    args.out.mkdir(parents=True, exist_ok=True)

    base = f"http://127.0.0.1:{args.port}"
    scenario = load_seed(args.scenario)
    with tempfile.TemporaryDirectory(prefix="vea-pr-shots-") as work:
        db_path, log = Path(work) / "demo.db", Path(work) / "server.log"
        with log.open("wb") as log_file:
            server = subprocess.Popen(
                [
                    "uv", "run", "--no-sync", "uvicorn", "vcenter_event_assistant.main:create_app",
                    "--factory", "--host", "127.0.0.1", "--port", str(args.port),
                ],
                cwd=REPOSITORY_ROOT,
                env=server_env(db_path, getattr(scenario, "SERVER_ENV", None)),
                stdout=log_file, stderr=subprocess.STDOUT,
            )
            try:
                wait_for_health(base, server, log)
                if scenario is not None and hasattr(scenario, "seed"):
                    client = login(base)
                    try:
                        scenario.seed(client, db_path)
                    finally:
                        client.close()
                result = subprocess.run(
                    ["node", str(HERE / "shoot.mjs"), base, str(args.out), args.scenario],
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
    if result.returncode != 0:
        return result.returncode
    print(f"{args.out} に書き出しました。")
    if args.publish and slug is not None:
        try:
            print(publish(args.out, args.publish, slug))
        except PublishError as exc:
            print(exc, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
