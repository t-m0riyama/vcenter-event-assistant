"""Test helpers for collector plugins.

アプリを起動せずにコレクタを検証するための道具である。**pytest には依存しない**
（stdlib だけで動く）ので、pytest でも unittest でも素のスクリプトでも使える。
pytest の fixture が欲しい場合だけ
:mod:`vcenter_event_assistant_plugin_api.testing.fixtures` を明示的に読み込む。

最小のスモークテストは 1 行である。

```python
from vcenter_event_assistant_plugin_api.testing import run_collect


async def test_collect():
    batch = await run_collect(TemperatureCollector(), mock_mode=True)
    assert batch.metrics
```

vCenter から読む経路も、偽の ServiceInstance で試せる。

```python
from vcenter_event_assistant_plugin_api.testing import (
    FakeServiceInstance,
    fake_host,
    run_collect,
)


async def test_samples_every_connected_host():
    si = FakeServiceInstance(
        hosts=[fake_host("host-1", "esxi-a"), fake_host("host-2", "esxi-b", connected=False)]
    )
    batch = await run_collect(TemperatureCollector(), connection=si)
    assert [sample.entity_moid for sample in batch.metrics] == ["host-1"]
```

:func:`run_collect` は本番と同じことを手元で確かめる。

- ``start`` → ``collect`` → ``stop`` を回す（``collect`` が失敗しても ``stop`` は呼ぶ）
- 返ってきたバッチをアプリと**同一の規則**で検証する。既定では warning でも落とす
  （warning はいずれも本番でデータが静かに失われるものである）
- vCenter 接続の開閉が釣り合っているかを検査する
- ``CreateContainerView`` で作ったビューが ``Destroy()`` されたかを検査する

Note:
    :class:`FakeServiceInstance` を ``vmware`` ヘルパ経由で使う場合、型名の解決に
    pyVmomi が必要である（``vcenter-event-assistant-plugin-api[vmware]``）。
    アプリのワーカー内では既に入っている。
"""

from __future__ import annotations

from vcenter_event_assistant_plugin_api.testing._assertions import (
    assert_batch_valid,
    assert_manifest_valid,
    run_collect,
)
from vcenter_event_assistant_plugin_api.testing._connection import (
    ConnectionLeakError,
    ConnectionLog,
    failing_connection,
    fake_connection,
    recording_connection,
)
from vcenter_event_assistant_plugin_api.testing._context import make_context, make_target
from vcenter_event_assistant_plugin_api.testing._stubs import (
    STUB_METRIC_KEY,
    STUB_PLUGIN_ID,
    StubCollector,
    stub_manifest,
    stub_metric_definition,
    stub_plugin_source,
)
from vcenter_event_assistant_plugin_api.testing._vmomi import (
    FakeContainerView,
    FakeEventCollector,
    FakeManagedObject,
    FakeServiceInstance,
    ViewLeakError,
    fake_datastore,
    fake_event,
    fake_host,
    fake_vm,
)

__all__ = [
    "STUB_METRIC_KEY",
    "STUB_PLUGIN_ID",
    "ConnectionLeakError",
    "ConnectionLog",
    "FakeContainerView",
    "FakeEventCollector",
    "FakeManagedObject",
    "FakeServiceInstance",
    "StubCollector",
    "ViewLeakError",
    "assert_batch_valid",
    "assert_manifest_valid",
    "fake_connection",
    "fake_datastore",
    "fake_event",
    "fake_host",
    "fake_vm",
    "failing_connection",
    "make_context",
    "make_target",
    "recording_connection",
    "run_collect",
    "stub_manifest",
    "stub_metric_definition",
    "stub_plugin_source",
]
