"""場面 collection-failures: 収集の失敗の表示（失敗中と過去の失敗）。

モックモードの vCenter（mock-demo-vc）に「過去の失敗」の関係の収集の状態を、API で足した vCenter
（lab-vc-02）に「失敗中」の状態を、DB に直接書く。組み込みのイベントのコレクタの実行の状態も、
同じように 2 台ぶん書く。スケジューラは止まっているので、撮るまで書き換わらない。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx

COLLECTOR = "builtin.vcenter.events"


def _ok(response: httpx.Response) -> dict | list:
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url} -> {response.status_code} {response.text}")
    return response.json()


def _time(delta: timedelta) -> str:
    # SQLAlchemy が SQLite に書く形（UTC、タイムゾーンなし）に合わせる。
    return (datetime.now(UTC) - delta).strftime("%Y-%m-%d %H:%M:%S.%f")


def seed(client: httpx.Client, db_path: Path) -> None:
    vcenters = _ok(client.get("/api/vcenters"))
    rows = vcenters if isinstance(vcenters, list) else vcenters["items"]
    past = next(row["id"] for row in rows if row["name"] == "mock-demo-vc").replace("-", "")
    failing = uuid4().hex
    with sqlite3.connect(db_path) as connection:
        # API は接続先の名前を DNS で引くので、モックの vCenter の行（暗号化したパスワードを含む）を写して足す。
        columns = [row[1] for row in connection.execute("PRAGMA table_info(vcenters)")]
        copied = ", ".join(columns)
        values = ", ".join("?" if name in ("id", "name", "host") else name for name in columns)
        params = [{"id": failing, "name": "lab-vc-02", "host": "lab-vc-02.example.local"}[name]
                  for name in columns if name in ("id", "name", "host")]
        connection.execute(f"INSERT INTO vcenters ({copied}) SELECT {values} FROM vcenters WHERE id = ?", [*params, past])
    states = (
        # 過去の失敗: 修正の前の失敗の後に、収集に成功している。
        (past, _time(timedelta(hours=9)), _time(timedelta(minutes=8)), "AttributeError: collector execution failed", 35, 76),
        # 失敗中: 認証の失敗が、最後の成功より新しい。
        (failing, _time(timedelta(minutes=6)), _time(timedelta(days=1)), "vim.fault.InvalidLogin: collector execution failed", 12, 20),
    )
    with sqlite3.connect(db_path) as connection:
        for vcenter_id, failure, success, error, objects, relations in states:
            connection.execute(
                """
                INSERT INTO inventory_sync_states (vcenter_id, first_success_at, last_started_at, last_success_at,
                    last_failure_at, last_error, object_count, relation_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vcenter_id) DO UPDATE SET last_success_at = excluded.last_success_at,
                    last_failure_at = excluded.last_failure_at, last_error = excluded.last_error,
                    object_count = excluded.object_count, relation_count = excluded.relation_count
                """,
                (vcenter_id, success, success, success, failure, error, objects, relations),
            )
        runs = (
            (past, "ok", _time(timedelta(minutes=2)), _time(timedelta(hours=3)), None),
            (failing, "failed", _time(timedelta(days=1)), _time(timedelta(minutes=4)),
             "ConnectionRefusedError: collector execution failed"),
        )
        for vcenter_id, status, success, failure, error in runs:
            connection.execute(
                """
                INSERT INTO collector_run_states (vcenter_id, collector_id, collector_version, status, last_started_at,
                    last_success_at, last_failure_at, events_inserted, metrics_inserted, logs_inserted, error_message)
                VALUES (?, ?, '', ?, ?, ?, ?, 0, 0, 0, ?)
                ON CONFLICT(vcenter_id, collector_id) DO UPDATE SET status = excluded.status,
                    last_success_at = excluded.last_success_at, last_failure_at = excluded.last_failure_at,
                    error_message = excluded.error_message
                """,
                (vcenter_id, COLLECTOR, status, max(success, failure), success, failure, error),
            )
