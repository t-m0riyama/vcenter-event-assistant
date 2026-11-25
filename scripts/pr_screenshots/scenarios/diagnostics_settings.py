"""場面 diagnostics-settings: 設定の「診断」のデモデータ。

モックモードの vCenter（mock-demo-vc）と ESXi（mock-esxi.local）に、診断用の鍵・接続先・実行の対象・
追加のコマンドを入れる。ホスト鍵の取得は実際に SSH で接続するので、ESXi の接続先だけは、
生成した鍵を承認済みのホスト鍵として DB に直接書く（承認済みの表示を撮るため）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import asyncssh
import httpx

SSH = "/api/diagnostics/ssh"


def _ok(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url} -> {response.status_code} {response.text}")
    return response.json()


def seed(client: httpx.Client, db_path: Path) -> None:
    key = _ok(client.post(f"{SSH}/credentials", json={"name": "diag-key"}))
    esxi = _ok(client.post(f"{SSH}/connections", json={
        "name": "ESXi 診断用", "host": "mock-esxi.local", "port": 22, "username": "diag-admin", "credential_id": key["id"],
    }))
    vcsa = _ok(client.post(f"{SSH}/connections", json={
        "name": "vCenter 診断用", "host": "mock.vcenter.local", "port": 22, "username": "root", "credential_id": key["id"],
    }))
    vcenters = _ok(client.get("/api/vcenters"))
    rows = vcenters if isinstance(vcenters, list) else vcenters["items"]
    vcenter_id = next(row["id"] for row in rows if row["name"] == "mock-demo-vc")
    for target in (
        {"product": "esxi", "host_moid": "mock-esxi", "host_name": "mock-esxi.local", "ssh_connection_id": esxi["id"]},
        {"product": "vcenter", "host_moid": None, "host_name": "mock.vcenter.local", "ssh_connection_id": vcsa["id"]},
    ):
        _ok(client.post("/api/diagnostics/targets", json={"vcenter_id": vcenter_id, **target}))
    for command in (
        {
            "title": "VMkernel のタグ",
            "description": "指定した VMkernel に付いた用途のタグを表示します。",
            "template": "esxcli network ip interface tag get -i {{vmk}}",
            "param_definitions": [{"name": "vmk", "type": "vmk"}],
        },
        {
            "title": "vMotion スタックでの疎通",
            "description": "vMotion 専用の TCP/IP スタックから疎通を確かめます。",
            "template": "vmkping -S vmotion -I {{vmk}} -c 3 {{target}}",
            "param_definitions": [{"name": "vmk", "type": "vmk"}, {"name": "target", "type": "ipv4"}],
        },
    ):
        _ok(client.post("/api/diagnostics/commands", json={"product": "esxi", **command}))

    host_key = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh").decode().strip()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE ssh_connections SET approved_key = ? WHERE id = ?", (host_key, esxi["id"].replace("-", ""))
        )
