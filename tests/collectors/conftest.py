"""collectors のテストで共有する補助。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import Mock

import pytest
from pyVmomi import SoapAdapter, vim


def _serialize_retrieve_call(collector: Mock) -> bytes:
    """偽の collector に渡した ``RetrievePropertiesEx`` の要求を、実機に送るときと同じく直列化する。

    偽の collector は直列化しないので、配列にタプルを渡す誤り（``pathSet`` や ``propSet``）は
    実機でしか出なかった（PR #399）。すべての呼び出しについて、FilterSpec の全体と取得のオプションを直列化する。
    view が Mock のときだけ、本物の ContainerView に替える（実機では本物が渡る）。
    """
    calls = collector.RetrievePropertiesEx.call_args_list
    assert calls, "RetrievePropertiesEx が呼ばれていない"
    xml = b""
    for call in calls:
        kwargs = call.kwargs
        for spec in kwargs["specSet"]:
            # テストが後で渡した spec を確かめられるよう、view は直列化の間だけ替えて戻す。
            replaced = [(o, o.obj) for o in spec.objectSet if isinstance(o.obj, Mock)]
            try:
                for object_spec, _original in replaced:
                    object_spec.obj = vim.view.ContainerView("view-1")
                part = SoapAdapter.Serialize(spec)
            finally:
                for object_spec, original in replaced:
                    object_spec.obj = original
            for prop in spec.propSet:
                for path in prop.pathSet:
                    assert f"<pathSet>{path}</pathSet>".encode() in part
            xml += part
        if kwargs.get("options") is not None:
            xml += SoapAdapter.Serialize(kwargs["options"])
    return xml


@pytest.fixture
def serialize_retrieve_call() -> Callable[[Any], bytes]:
    return _serialize_retrieve_call
