"""Durable publication of isolated plugin generations."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import uuid
from pathlib import Path
from typing import Any

_CATALOG = ".published.json"
_GENERATIONS = ".generations"


def read_catalog(root: Path) -> dict[str, Any]:
    try:
        with (root / _CATALOG).open(encoding="utf-8") as source:
            catalog = json.load(source)
    except FileNotFoundError as exc:
        raise RuntimeError("initialize the plugin volume before starting in isolation mode") from exc
    if catalog.get("format") != 1 or not isinstance(catalog.get("distributions"), dict):
        raise RuntimeError("invalid plugin publication catalog")
    return catalog


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_catalog(root: Path, catalog: dict[str, Any]) -> None:
    temp = root / f".published-{uuid.uuid4().hex}.tmp"
    try:
        with temp.open("x", encoding="utf-8") as output:
            json.dump(catalog, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        temp.replace(root / _CATALOG)
        _sync_directory(root)
    finally:
        temp.unlink(missing_ok=True)


def published_paths(root: Path) -> list[str]:
    return list(installed_paths(root).values())


def installed_paths(root: Path) -> dict[tuple[str, str], str]:
    catalog = read_catalog(root)
    return {
        (distribution, version): str(root / relative)
        for distribution, versions in catalog["distributions"].items()
        for version, relative in versions.items()
    }


def _generation_dir(root: Path) -> Path:
    path = root / _GENERATIONS
    path.mkdir(exist_ok=True)
    path.chmod(0o755)
    return path


def _sync_tree(path: Path) -> None:
    for parent, _, files in os.walk(path, topdown=False):
        for name in files:
            with (Path(parent) / name).open("rb") as source:
                os.fsync(source.fileno())
        _sync_directory(Path(parent))


def publish(
    root: Path, staging: Path, distribution: str, version: str, *, source: str,
) -> Path:
    catalog = read_catalog(root)
    _require_clean_catalog(catalog)
    generation_dir = _generation_dir(root)
    final = generation_dir / uuid.uuid4().hex
    _sync_tree(staging)
    staging.rename(final)
    _sync_directory(generation_dir)
    catalog["distributions"].setdefault(distribution, {})[version] = str(final.relative_to(root))
    catalog["pending"] = {
        "operation": "install",
        "distribution": distribution,
        "version": version,
        "source": source,
        "path": str(final),
    }
    _write_catalog(root, catalog)
    return final


def _require_clean_catalog(catalog: dict[str, Any]) -> None:
    if catalog["pending"] is not None:
        raise RuntimeError("plugin publication must be reconciled before making changes")


def unpublish(root: Path, distribution: str) -> bool:
    catalog = read_catalog(root)
    _require_clean_catalog(catalog)
    removed = catalog["distributions"].pop(distribution, None) is not None
    catalog["pending"] = {"operation": "uninstall", "distribution": distribution}
    _write_catalog(root, catalog)
    return removed


def clear_pending(root: Path) -> None:
    catalog = read_catalog(root)
    catalog["pending"] = None
    _write_catalog(root, catalog)


def remove_retired_generations(root: Path, keep: set[str]) -> None:
    path = root / _GENERATIONS
    if path.is_dir():
        for generation in path.iterdir():
            if str(generation) not in keep:
                shutil.rmtree(generation)


def _copy_legacy(source: Path, destination: Path) -> None:
    destination.mkdir()
    destination.chmod(0o755)
    for entry in source.iterdir():
        mode = entry.lstat().st_mode
        target = destination / entry.name
        if stat.S_ISDIR(mode):
            _copy_legacy(entry, target)
        elif stat.S_ISREG(mode):
            shutil.copyfile(entry, target)
            target.chmod(0o755 if mode & stat.S_IXUSR else 0o644)
        else:
            raise RuntimeError(f"unsupported entry in legacy plugin tree: {entry}")


def migrate(legacy: Path, root: Path) -> None:
    if (root / _CATALOG).exists():
        read_catalog(root)
        return
    if not legacy.parent.is_dir() or not root.is_dir() or legacy.resolve() == root.resolve():
        raise RuntimeError("mount the existing data and a separate plugin destination")
    root.chmod(0o755)
    generations = _generation_dir(root)
    remove_retired_generations(root, set())
    catalog: dict[str, Any] = {"format": 1, "distributions": {}, "pending": None}
    if legacy.is_symlink() or (legacy.exists() and not legacy.is_dir()):
        raise RuntimeError("invalid legacy plugin directory")
    if legacy.is_dir():
        for distribution in sorted(legacy.iterdir()):
            if distribution.name.startswith(".") or not distribution.is_dir():
                continue
            if distribution.is_symlink():
                raise RuntimeError(f"unsupported legacy plugin directory: {distribution}")
            for version in sorted(distribution.iterdir()):
                if version.name.startswith(".") or not version.is_dir():
                    continue
                if version.is_symlink():
                    raise RuntimeError(f"unsupported legacy plugin directory: {version}")
                target = generations / uuid.uuid4().hex
                _copy_legacy(version, target)
                _sync_tree(target)
                catalog["distributions"].setdefault(distribution.name, {})[version.name] = str(
                    target.relative_to(root)
                )
    _sync_directory(generations)
    _write_catalog(root, catalog)


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize or migrate the plugin volume")
    parser.add_argument("legacy", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    migrate(args.legacy, args.destination)


if __name__ == "__main__":
    main()
