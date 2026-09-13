"""``CollectionContext`` / ``VCenterTarget`` の組み立て。

アプリ側が渡すものと同じ形を、必要なフィールドだけ指定して作れるようにする。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from vcenter_event_assistant_plugin_api import (
    CollectionContext,
    ConnectionFactory,
    VCenterTarget,
)
from vcenter_event_assistant_plugin_api.testing._connection import fake_connection
from vcenter_event_assistant_plugin_api.testing._vmomi import FakeServiceInstance

__all__ = ["make_context", "make_target"]

#: ``connection`` を省略したときに既定を使うことを示す標識。``None`` を明示的に渡す
#: ケースと区別するために必要。
_DEFAULT = object()


def make_target(
    *,
    id: UUID | None = None,  # noqa: A002 - VCenterTarget のフィールド名に合わせる
    name: str = "vcenter-01",
    host: str = "vc.example.com",
    protocol: str = "https",
    port: int = 443,
    username: str = "svc-collector@vsphere.local",
    verify_ssl: bool = True,
) -> VCenterTarget:
    """収集対象の vCenter を表す :class:`VCenterTarget` を作る。"""
    return VCenterTarget(
        id=id if id is not None else uuid4(),
        name=name,
        host=host,
        protocol=protocol,
        port=port,
        username=username,
        verify_ssl=verify_ssl,
    )


def make_context(
    *,
    target: VCenterTarget | None = None,
    config: Mapping[str, Any] | None = None,
    previous_cursor: str | None = None,
    mock_mode: bool = False,
    connection: Any = _DEFAULT,
) -> CollectionContext:
    """コレクタに渡す :class:`CollectionContext` を作る。

    Args:
        target: 収集対象。省略時は :func:`make_target` の既定値。
        config: プラグイン設定。管理画面や TOML から来るものに相当する。
        previous_cursor: 前回のカーソル。``None`` は初回。
        mock_mode: ``MOCK_MODE=true`` 相当。接続は開かれない。
        connection: ``si`` として渡すオブジェクト、または
            ``ConnectionFactory``（引数なしで async context manager を返す呼び出し可能）。
            省略時は空の :class:`FakeServiceInstance` を渡す**動く**ファクトリを張る。

    Note:
        既定で動く接続ファクトリが入るのが要点である。``lambda: None`` を置くと
        非 mock 経路がそもそも試せず、テストが通っても本番で落ちる。
    """
    if connection is _DEFAULT:
        factory: ConnectionFactory = fake_connection(FakeServiceInstance())
    elif callable(connection):
        factory = connection
    else:
        factory = fake_connection(connection)

    return CollectionContext(
        target=target if target is not None else make_target(),
        config=dict(config or {}),
        previous_cursor=previous_cursor,
        open_vcenter_connection=factory,
        mock_mode=mock_mode,
    )
