"""Optional pytest fixtures for collector plugin authors.

**これは opt-in である。** ``pytest11`` の entry point は意図的に登録していない
（登録するとこのパッケージを入れた全ての pytest セッションに勝手に載る）。使うには
プラグイン側の ``conftest.py`` で明示的に読み込むこと。

```python
# conftest.py
pytest_plugins = ["vcenter_event_assistant_plugin_api.testing.fixtures"]
```

これで ``service_instance`` / ``context`` / ``mock_context`` が使える。

```python
async def test_collect(service_instance, context):
    service_instance._objects["HostSystem"].append(fake_host("host-1", "esxi-a"))
    batch = await run_collect(TemperatureCollector(), context)
    assert batch.metrics
```

このモジュールは :mod:`vcenter_event_assistant_plugin_api.testing` 本体からは
import されない。本体は stdlib だけで動き、pytest を必要としない。
"""

from __future__ import annotations

from typing import Any

import pytest

from vcenter_event_assistant_plugin_api import CollectionContext, VCenterTarget
from vcenter_event_assistant_plugin_api.testing import (
    FakeServiceInstance,
    fake_connection,
    make_context,
    make_target,
)

__all__ = ["context", "mock_context", "service_instance", "target"]


@pytest.fixture
def target() -> VCenterTarget:
    """収集対象の vCenter。"""
    return make_target()


@pytest.fixture
def service_instance() -> FakeServiceInstance:
    """空の偽 ServiceInstance。テスト側でホストやデータストアを足す。"""
    return FakeServiceInstance()


@pytest.fixture
def context(
    target: VCenterTarget, service_instance: FakeServiceInstance
) -> CollectionContext:
    """``service_instance`` へ繋がる、非 mock の収集コンテキスト。"""
    return make_context(target=target, connection=fake_connection(service_instance))


@pytest.fixture
def mock_context(target: VCenterTarget) -> CollectionContext:
    """``MOCK_MODE=true`` 相当のコンテキスト。

    接続を開こうとすると失敗するので、mock 経路が本当に接続を開いていないことも
    同時に確かめられる。
    """

    def _must_not_connect() -> Any:
        raise AssertionError("mock_mode must not open a vCenter connection")

    return make_context(
        target=target, mock_mode=True, connection=_must_not_connect
    )
