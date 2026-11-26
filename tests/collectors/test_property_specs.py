"""PropertySpec を補助関数だけで作ることと、その要求が直列化できることを確かめる。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pyVmomi import SoapAdapter, vim

from vcenter_event_assistant.collectors.property_specs import property_spec

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "src" / "vcenter_event_assistant" / "collectors" / "property_specs.py"
# pyVmomi を使いうるコード。テストは偽の値を組み立てるので対象にしない。
SCANNED = [ROOT / "src", ROOT / "scripts", *sorted((ROOT / "packages").glob("*/src"))]


def test_property_spec_lists_paths_and_serializes() -> None:
    spec = property_spec(vim.VirtualMachine, ("name", "runtime.host"))
    assert isinstance(spec.pathSet, list)
    xml = SoapAdapter.Serialize(spec)
    assert b"<pathSet>name</pathSet>" in xml
    assert b"<pathSet>runtime.host</pathSet>" in xml


def test_property_spec_rejects_a_single_string() -> None:
    with pytest.raises(TypeError):
        property_spec(vim.VirtualMachine, "name")


def _offenders(path: Path) -> list[str]:
    where = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        # 別名や getattr を含め、PropertySpec という名前への参照をすべて拾う。
        name = (
            node.id if isinstance(node, ast.Name)
            else node.attr if isinstance(node, ast.Attribute)
            else node.value if isinstance(node, ast.Constant) and isinstance(node.value, str)
            else None
        )
        if name == "PropertySpec":
            found.append(f"{where}:{node.lineno}")
        # 作った後に pathSet を差し替えると、補助関数の list を回避できる。
        if (isinstance(node, ast.Attribute) and node.attr == "pathSet" and isinstance(node.ctx, ast.Store)) or (
            isinstance(node, ast.Constant) and node.value == "pathSet"  # setattr(spec, "pathSet", ...)
        ):
            found.append(f"{where}:{node.lineno}（pathSet への代入）")
    return found


def test_property_spec_is_only_built_by_the_helper() -> None:
    """PropertySpec を直接作ると、タプルを渡して実機でだけ失敗する誤りを繰り返しうる（PR #399）。"""
    files = [path for base in SCANNED for path in sorted(base.rglob("*.py")) if path != HELPER]
    assert len(files) > 50, "走査の対象が見つからない（パスが変わった可能性）"
    offenders = [hit for path in files for hit in _offenders(path)]
    assert offenders == [], f"collectors/property_specs.py の property_spec() を使ってください: {offenders}"


@pytest.mark.parametrize(
    "source",
    [
        "x = vmodl.query.PropertyCollector.PropertySpec(type=1, pathSet=['a'])",
        "PS = pc.PropertySpec\nx = PS(type=1)",
        "x = getattr(pc, 'PropertySpec')(type=1)",
        "x = pc.PropertySpec\\\n    (type=1)",
        "spec.pathSet = ('a',)",
        "setattr(spec, 'pathSet', ('a',))",
    ],
)
def test_offenders_catch_indirect_uses(tmp_path: Path, source: str) -> None:
    path = tmp_path / "probe.py"
    path.write_text(source + "\n", encoding="utf-8")
    assert _offenders(path)
