"""登録済みの vCenter の構成を 2 回読み、件数・大きさ・時間だけを表示する。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from time import monotonic, sleep

from pyVmomi import vim
from pyVmomi.VmomiJSONEncoder import VmomiJSONEncoder
from pyVmomi.VmomiSupport import ManagedObject
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vcenter_event_assistant.auth.timeutil import utcnow
from vcenter_event_assistant.collectors.config_values import (
    VM_DETAIL_PATHS,
    diff_config,
    disk_backing_root,
    normalize_disk_uuid,
)
from vcenter_event_assistant.collectors.connection import connect_vcenter, disconnect
from vcenter_event_assistant.collectors.inventory_config import (
    ConfigObservation,
    PropertyRow,
    normalize_details,
    normalize_overview,
    overview_paths,
    read_overview,
    read_vm_details,
)
from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.settings import Settings, get_settings
from vcenter_event_assistant.settings_binding import bind_settings

_NO_DEADLINE = float("inf")


class _PropertyEncoder(VmomiJSONEncoder):
    def default(self, obj):
        if isinstance(obj, ManagedObject):
            # サイズの測定中に参照先の属性を追加で取りに行かない。
            return str(obj)
        return super().default(obj)


def _path_stats(rows: list[PropertyRow], path: str) -> str:
    present = missing = absent = empty = 0
    for row in rows:
        if path in row.props:
            present += 1
            value = row.props[path]
            empty += isinstance(value, list) and not value
        if path in row.missing:
            missing += 1
        if path not in row.props and path not in row.missing:
            absent += 1
    return f"propSet={present} missingSet={missing} absent={absent} empty_array={empty}"


def _size_by_type(stage: str, rows: list[PropertyRow], *types: str) -> None:
    by_type: dict[str, list[dict]] = {kind: [] for kind in types}
    for row in rows:
        by_type.setdefault(row.ref._wsdlName, []).append(row.props)
    for kind, props in sorted(by_type.items()):
        size = len(
            json.dumps(
                props, cls=_PropertyEncoder, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        )
        print(f"{stage} {kind} objects={len(props)} bytes={size}")


def _probe_paths(content) -> tuple[dict, str]:
    new = "configurationEx"
    old = "configuration"
    paths = {}
    cluster_failures = False
    for kind, attrs in overview_paths(new).items():
        for path in attrs:
            try:
                rows, _ = read_overview(
                    content,
                    {kind: ("name",) if path == "name" else ("name", path)},
                    deadline=_NO_DEADLINE,
                )
            except Exception as exc:
                print(f"stage1 {kind._wsdlName} {path} {type(exc).__name__}")
                cluster_failures |= path.startswith(new + ".")
            else:
                print(f"stage1 {kind._wsdlName} {path} ok {_path_stats(rows, path)}")
                paths.setdefault(kind, []).append(path)

    if cluster_failures:
        for kind, attrs in overview_paths(old).items():
            legacy_paths = [path for path in attrs if path.startswith(old + ".")]
            if not legacy_paths:
                continue
            paths[kind] = [
                path for path in paths.get(kind, []) if not path.startswith(new + ".")
            ]
            for path in legacy_paths:
                try:
                    rows, _ = read_overview(
                        content, {kind: ("name", path)}, deadline=_NO_DEADLINE
                    )
                except Exception as exc:
                    print(f"stage1 {kind._wsdlName} {path} {type(exc).__name__}")
                else:
                    print(
                        f"stage1 {kind._wsdlName} {path} ok {_path_stats(rows, path)}"
                    )
                    paths[kind].append(path)
    return {
        kind: tuple(attrs) for kind, attrs in paths.items() if attrs
    }, old if cluster_failures else new


def _report_disk_backings(rows: list[PropertyRow]) -> None:
    with_parent = different_thin = 0
    with_uuid = without_root_uuid = different_uuid = 0
    for row in rows:
        for device in row.get("config.hardware.device") or ():
            if not isinstance(device, vim.vm.device.VirtualDisk):
                continue
            backing = device.backing
            try:
                parent = getattr(backing, "parent", None)
            except Exception:
                continue
            if parent is not None:
                with_parent += 1
            root = disk_backing_root(backing)
            if root is None:
                continue
            root_uuid = normalize_disk_uuid(getattr(root, "uuid", None))
            if root_uuid is None:
                without_root_uuid += 1
            else:
                with_uuid += 1
            # 差分ディスクの UUID が元のディスクと違うか（親を付け替える操作の見積もり）。
            current_uuid = normalize_disk_uuid(getattr(backing, "uuid", None))
            if (
                parent is not None
                and root_uuid is not None
                and current_uuid is not None
                and current_uuid != root_uuid
            ):
                different_uuid += 1
            if parent is not None and getattr(
                backing, "thinProvisioned", None
            ) != getattr(root, "thinProvisioned", None):
                different_thin += 1
    print(
        f"stage2 disks_with_parent={with_parent} disks_with_different_thin={different_thin}"
    )

    print(
        f"stage2 disks_with_uuid={with_uuid} disks_without_root_uuid={without_root_uuid}"
        f" disks_with_different_uuid={different_uuid}"
    )


def _sample(content, paths: dict, cluster_path: str) -> ConfigObservation:
    start = monotonic()
    rows, started_at = read_overview(content, paths, deadline=_NO_DEADLINE)
    print(f"stage1 seconds={monotonic() - start:.3f}")
    _size_by_type(
        "stage1", rows, "HostSystem", "ClusterComputeResource", "VirtualMachine"
    )
    sample = ConfigObservation("", started_at, started_at, cluster_path)
    readable = normalize_overview(rows, sample)
    refs = [
        row.ref
        for row in rows
        if row.ref._wsdlName == "VirtualMachine" and row.ref._moId in sample.objects
    ]
    start = monotonic()
    try:
        details = read_vm_details(content, refs, deadline=_NO_DEADLINE)
    except Exception as exc:
        print(f"stage2 seconds={monotonic() - start:.3f} {type(exc).__name__}")
        return sample
    print(f"stage2 seconds={monotonic() - start:.3f} requested={len(refs)}")
    print(f"stage2 ManagedObjectNotFound={len(details.removed)}")
    detail_rows = list(details.rows.values())
    _report_disk_backings(detail_rows)
    _size_by_type("stage2", detail_rows, vim.VirtualMachine._wsdlName)
    for path in VM_DETAIL_PATHS:
        print(f"stage2 VirtualMachine {path} {_path_stats(detail_rows, path)}")
    overview_versions = {
        row.ref._moId: str(version)
        for row in rows
        if row.ref._wsdlName == "VirtualMachine"
        and row.ref._moId in sample.objects
        and (version := row.get("config.changeVersion")) is not None
    }
    normalize_details(sample, readable, details)
    sample.change_versions = overview_versions
    sample.observed_at = utcnow()
    return sample


def _compare(before: ConfigObservation, after: ConfigObservation) -> None:
    counts: Counter[tuple[str, str | None]] = Counter()
    for moid, category in before.values.keys() & after.values.keys():
        key = moid, category
        for diff in diff_config(category, before.values[key], after.values[key]):
            counts[category, diff.attribute] += 1
    for (category, attribute), count in sorted(
        counts.items(), key=lambda item: (item[0][0], item[0][1] or "")
    ):
        print(f"changed {category} {attribute or 'element'} count={count}")

    common = before.change_versions.keys() & after.change_versions.keys()
    changed = sum(
        before.change_versions[vm] != after.change_versions[vm] for vm in common
    )
    print(f"changed config.changeVersion count={changed}")


def _read_only_settings(settings: Settings) -> Settings:
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite":
        return settings
    database = url.database or ":memory:"
    if database == ":memory:" or url.query.get("mode") == "memory":
        raise ValueError("SQLite のファイルが必要です。")
    # 通常のファイル名と、すでに file: URI の接続先に対応する。
    uri = (
        database
        if url.query.get("uri") == "true" and database.startswith("file:")
        else Path(database).resolve().as_uri()
    )
    url = url.set(database=uri).update_query_dict({"mode": "ro", "uri": "true"})
    return settings.model_copy(
        update={"database_url": url.render_as_string(hide_password=False)}
    )


async def _find_vcenter(name: str, settings: Settings) -> VCenter | None:
    engine = create_async_engine(_read_only_settings(settings).database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            if session.get_bind().dialect.name == "postgresql":
                await session.execute(text("SET TRANSACTION READ ONLY"))
            return await session.scalar(select(VCenter).where(VCenter.name == name))
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vcenter_name", help="登録済みの vCenter の名前")
    parser.add_argument(
        "--interval-seconds", type=int, default=300, help="観測の間隔（既定 300 秒）"
    )
    args = parser.parse_args(argv)
    if args.interval_seconds < 0:
        parser.error("--interval-seconds は 0 以上にしてください。")
    try:
        settings = get_settings()
        bind_settings(settings)
        center = asyncio.run(_find_vcenter(args.vcenter_name, settings))
        if center is None:
            print("登録済みの vCenter が見つかりません。", file=sys.stderr)
            return 1
        si = connect_vcenter(
            host=center.host,
            protocol=center.protocol,
            port=center.port,
            username=center.username,
            password=center.password,
            verify_ssl=center.verify_ssl,
            proxy_url=settings.vcenter_http_proxy,
            ca_bundle_path=settings.vcenter_ca_bundle,
            http_connection_timeout=settings.inventory_sync_timeout_seconds,
        )
        try:
            content = si.RetrieveContent()
            paths, cluster_path = _probe_paths(content)
            before = _sample(content, paths, cluster_path)
            sleep(args.interval_seconds)
            after = _sample(content, paths, cluster_path)
            _compare(before, after)
        finally:
            disconnect(si)
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
