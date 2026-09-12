#!/usr/bin/env python3
"""vCenter のイベントカタログ（``EventManager.description.eventInfo``）を JSON に出力する。

イベント種別ガイド（``data/seed/event-type-guides-priority-*.json``）の本文を
公式情報に基づいて書くための **一次情報取得用** スクリプト。vCenter へは
**読み取りのみ** で接続する。

登録済み vCenter は ``DATABASE_URL`` の DB から読む（パスワードは
:class:`~vcenter_event_assistant.db.encrypted_string.EncryptedString` により
ORM 読み出し時点で復号される）。

Usage:
    .venv/bin/python scripts/dump_event_catalog.py --out /tmp/catalog.json
    .venv/bin/python scripts/dump_event_catalog.py --locale ja --vcenter vcenter8-01

出力は ``key`` / ``description`` / ``longDescription`` / ``fullFormat`` /
``category`` に加え、ガイドの ``event_type`` と突き合わせ可能な ``event_type`` を持つ配列。取得結果には環境固有の情報が含まれうるため
**リポジトリにはコミットしない**こと。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


_CATALOG_FIELDS = ("key", "description", "longDescription", "fullFormat", "category")

# ``key`` が型オブジェクトのときの repr（例: <class 'pyVmomi.VmomiSupport.vim.event.VmPoweredOnEvent'>）
_TYPE_KEY_RE = re.compile(r"'pyVmomi\.VmomiSupport\.(?P<name>[\w.]+)'")


def _as_text(value: Any) -> str | None:
    """pyVmomi の型・enum 等を JSON に載せられる文字列へ寄せる。"""
    if value is None or isinstance(value, str):
        return value
    return str(value)


def _event_type_of(key: str | None, full_format: str | None) -> str | None:
    """カタログ 1 行から、ガイドの ``event_type`` と突き合わせ可能な型名を求める。

    型付きイベントの ``key`` は型オブジェクト（``vim.event.VmPoweredOnEvent``）、
    ``ExtendedEvent`` は全行が同じ型なので ``fullFormat`` 先頭の ID（``ad.event.Xxx``）を使う。
    """
    if key:
        matched = _TYPE_KEY_RE.search(key)
        name = matched.group("name") if matched else None
        if name and not name.endswith(".ExtendedEvent"):
            return name
    if full_format and "|" in full_format:
        return full_format.split("|", 1)[0].strip() or None
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="出力先 JSON ファイルパス",
    )
    parser.add_argument(
        "--vcenter",
        default=None,
        help="対象 vCenter の name（未指定なら is_enabled な先頭の1件）",
    )
    parser.add_argument(
        "--locale",
        default=None,
        help="取得ロケール（例: ja）。設定に失敗してもセッション既定のまま続行する",
    )
    return parser.parse_args(argv)


async def load_vcenter(name: str | None) -> dict[str, Any]:
    """DB から接続に必要な vCenter 情報を平文で取り出す。"""
    from sqlalchemy import select

    from vcenter_event_assistant.db.models import VCenter
    from vcenter_event_assistant.db.session import session_scope

    stmt = select(VCenter)
    if name:
        stmt = stmt.where(VCenter.name == name)
    else:
        stmt = stmt.where(VCenter.is_enabled.is_(True))
    stmt = stmt.order_by(VCenter.created_at)

    async with session_scope() as session:
        vc = (await session.scalars(stmt)).first()
        if vc is None:
            target = f"name={name!r}" if name else "is_enabled=True"
            raise SystemExit(f"対象の vCenter が DB に見つかりません（{target}）")
        return {
            "name": vc.name,
            "host": vc.host,
            "protocol": vc.protocol,
            "port": vc.port,
            "username": vc.username,
            "password": vc.password,
            "verify_ssl": vc.verify_ssl,
        }


def dump_catalog(vc: dict[str, Any], locale: str | None) -> list[dict[str, Any]]:
    """vCenter に接続してイベントカタログを読み出す（ブロッキング）。"""
    from vcenter_event_assistant.collectors.connection import (
        connect_vcenter,
        disconnect,
    )
    from vcenter_event_assistant.settings_binding import require_settings

    settings = require_settings()
    si = connect_vcenter(
        host=vc["host"],
        protocol=vc["protocol"],
        port=vc["port"],
        username=vc["username"],
        password=vc["password"],
        proxy_url=settings.vcenter_http_proxy,
        verify_ssl=vc["verify_ssl"],
        ca_bundle_path=settings.vcenter_ca_bundle,
    )
    try:
        content = si.RetrieveContent()
        if locale:
            try:
                content.sessionManager.SetLocale(locale)
                # ロケールは再取得後の description に反映される。
                content = si.RetrieveContent()
            except Exception as exc:  # noqa: BLE001 - ロケール未対応は致命的でない
                print(
                    f"警告: ロケール {locale!r} を設定できませんでした: {exc}",
                    file=sys.stderr,
                )
        event_info = content.eventManager.description.eventInfo
        rows: list[dict[str, Any]] = []
        for detail in event_info:
            row = {
                field: _as_text(getattr(detail, field, None))
                for field in _CATALOG_FIELDS
            }
            row["event_type"] = _event_type_of(row["key"], row["fullFormat"])
            rows.append(row)
        return rows
    finally:
        disconnect(si)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    from vcenter_event_assistant.settings import get_settings
    from vcenter_event_assistant.settings_binding import bind_settings

    bind_settings(get_settings())

    vc = await load_vcenter(args.vcenter)
    print(f"接続先: {vc['name']} ({vc['host']}:{vc['port']})", file=sys.stderr)

    entries = await asyncio.to_thread(dump_catalog, vc, args.locale)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"OK: {len(entries)} 件を {args.out} に出力しました", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
