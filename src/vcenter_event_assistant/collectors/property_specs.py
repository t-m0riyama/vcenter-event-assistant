"""PropertyCollector に渡す PropertySpec を作る。

pyVmomi は list でない配列（タプルなど）を 1 つの値として直列化しようとし、要求を組み立てられない
（``AttributeError: 'tuple' object has no attribute 'replace'``）。偽の PropertyCollector を使う
テストでは直列化を通らないので、この誤りは実機でしか見つからなかった（PR #399）。
PropertySpec はこの関数だけで作る。``tests/collectors/test_property_specs.py`` が、ほかの場所で
``PropertySpec`` を参照していないことを確かめる。要求の全体（FilterSpec と取得のオプション）が
直列化できることは、``tests/collectors/conftest.py`` の ``serialize_retrieve_call`` で確かめる。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pyVmomi import vmodl


def property_spec(kind: Any, paths: Iterable[str]) -> Any:
    """``kind`` の ``paths`` を読む PropertySpec を返す。``pathSet`` は必ず list にする。"""
    if isinstance(paths, str):
        # 文字列は 1 文字ずつのパスに分かれ、実機で InvalidProperty になる。
        raise TypeError("paths にはパスの並びを渡してください（文字列 1 つではなく）。")
    return vmodl.query.PropertyCollector.PropertySpec(type=kind, pathSet=list(paths))
