"""CI の PostgreSQL の手順を、手元の Docker の PostgreSQL で同じように流す。

正本は ``.github/workflows/ci.yml`` で、このスクリプトはテストの一覧を持たない。
``services.postgres`` を持つジョブのうち、環境変数で ``job.services.postgres.ports`` を
参照する手順を取り出し、その ``run`` を手元のポートに置き換えて順に実行する。

使い方::

    uv run python scripts/ci_postgres_local.py          # コンテナが無ければ立ててから全手順を流す
    uv run python scripts/ci_postgres_local.py --list   # 流す手順とコマンドを表示するだけ
    uv run python scripts/ci_postgres_local.py --stop   # 流したあとでコンテナを止める
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
CONTAINER = "vea-pg-test"
DEFAULT_PORT = 55432
_PORT_EXPRESSION = re.compile(r"\$\{\{\s*job\.services\.postgres\.ports\['5432'\]\s*\}\}")


@dataclass(frozen=True)
class PostgresService:
    image: str
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class PostgresStep:
    job: str
    name: str
    run: str
    env: dict[str, str]


def load_workflow(path: Path = WORKFLOW) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        workflow = yaml.safe_load(file)
    if not isinstance(workflow, dict):
        raise ValueError(f"{path} の形を読めません")
    return workflow


def _postgres_jobs(workflow: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    jobs = workflow.get("jobs") or {}
    return [
        (name, job)
        for name, job in jobs.items()
        if isinstance(job, dict) and "postgres" in (job.get("services") or {})
    ]


def postgres_service(workflow: dict[str, Any]) -> PostgresService:
    """CI のサービスと同じイメージ・ユーザー・DB を返す。ジョブが複数でも設定は同じ前提。"""
    jobs = _postgres_jobs(workflow)
    if not jobs:
        raise ValueError("services.postgres を持つジョブがありません")
    service = jobs[0][1]["services"]["postgres"]
    env = service.get("env") or {}
    return PostgresService(
        image=str(service["image"]),
        user=str(env["POSTGRES_USER"]),
        password=str(env["POSTGRES_PASSWORD"]),
        database=str(env["POSTGRES_DB"]),
    )


def postgres_steps(workflow: dict[str, Any], port: int) -> list[PostgresStep]:
    """PostgreSQL のポートを環境変数で参照する手順を、手元のポートに置き換えて返す。"""
    steps: list[PostgresStep] = []
    for job_name, job in _postgres_jobs(workflow):
        for index, step in enumerate(job.get("steps") or [], start=1):
            env = {str(key): str(value) for key, value in (step.get("env") or {}).items()}
            if "run" not in step or not any(_PORT_EXPRESSION.search(value) for value in env.values()):
                continue
            steps.append(
                PostgresStep(
                    job=job_name,
                    name=str(step.get("name") or f"{job_name} の手順 {index}"),
                    run=str(step["run"]).strip(),
                    env={key: _PORT_EXPRESSION.sub(str(port), value) for key, value in env.items()},
                )
            )
    return steps


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def published_ports(docker_port_output: str) -> set[int]:
    """``docker port <名前> 5432/tcp`` の出力（``0.0.0.0:55432`` や ``[::]:55432`` の行）からホストのポートを返す。"""
    ports: set[int] = set()
    for line in docker_port_output.splitlines():
        _, separator, port = line.strip().rpartition(":")
        if separator and port.isdigit():
            ports.add(int(port))
    return ports


def ensure_container(service: PostgresService, port: int) -> None:
    """コンテナが動いていなければ立て、接続を受け付けるまで待つ。

    動いているコンテナは、指定のポートで公開しているときだけ使う。接続の確認はコンテナの中で
    行うので、ポートが違っても通ってしまい、テストだけが別のポートにつなぐことになるためである。
    """
    running = _docker("ps", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Names}}").stdout.strip()
    if running == CONTAINER:
        ports = published_ports(_docker("port", CONTAINER, "5432/tcp", check=False).stdout)
        if port not in ports:
            shown = ", ".join(str(item) for item in sorted(ports)) or "なし"
            raise RuntimeError(
                f"{CONTAINER} はポート {shown} で動いていて、指定のポート {port} では公開していません。"
                f"`--port` を合わせるか、`docker stop {CONTAINER}` で止めてから流し直してください。"
            )
    else:
        print(f"PostgreSQL のコンテナ {CONTAINER} を {service.image} で起動します（ポート {port}）。")
        _docker(
            "run", "-d", "--rm", "--name", CONTAINER,
            "-e", f"POSTGRES_USER={service.user}",
            "-e", f"POSTGRES_PASSWORD={service.password}",
            "-e", f"POSTGRES_DB={service.database}",
            "-p", f"{port}:5432",
            service.image,
        )
    for _ in range(60):
        ready = _docker(
            "exec", CONTAINER, "pg_isready", "-h", "127.0.0.1", "-U", service.user, "-d", service.database,
            check=False,
        )
        if ready.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError(f"{CONTAINER} が 60 秒たっても接続を受け付けません")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"手元で使うポート（既定 {DEFAULT_PORT}）")
    parser.add_argument("--list", action="store_true", help="流す手順とコマンドを表示して終わる")
    parser.add_argument("--stop", action="store_true", help="流し終えたらコンテナを止める")
    args = parser.parse_args(argv)

    workflow = load_workflow()
    steps = postgres_steps(workflow, args.port)
    if not steps:
        print("PostgreSQL を使う手順が ci.yml にありません。", file=sys.stderr)
        return 1
    if args.list:
        for step in steps:
            print(f"# {step.name}\n{step.run}\n")
        return 0

    try:
        ensure_container(postgres_service(workflow), args.port)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    failed: list[str] = []
    try:
        for step in steps:
            print(f"\n=== {step.name}", flush=True)
            result = subprocess.run(
                ["bash", "-c", step.run], cwd=REPOSITORY_ROOT, env={**os.environ, **step.env}, check=False
            )
            if result.returncode != 0:
                failed.append(step.name)
    finally:
        if args.stop:
            _docker("stop", CONTAINER, check=False)

    print(f"\n{len(steps) - len(failed)}/{len(steps)} 手順が成功しました。")
    for name in failed:
        print(f"失敗: {name}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
