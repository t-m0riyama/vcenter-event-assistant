# vcenter-event-assistant-plugin-api

[vCenter Event Assistant](https://github.com/t-m0riyama/vcenter-event-assistant) の
コレクタプラグインを書くための契約とヘルパである。**依存パッケージを持たない。**

プラグインはこのパッケージだけに依存する。アプリ本体（`vcenter_event_assistant`）を
import してはならない。

## クイックスタート

```bash
pip install vcenter-event-assistant-plugin-api
python -m vcenter_event_assistant_plugin_api.scaffold my-sensor-collector --kind metric
cd my-sensor-collector
pytest -q          # アプリも vCenter も起動せずに通る
```

実装するのは**同期のメソッド 1 つ**だけである。

```python
from vcenter_event_assistant_plugin_api import MetricCollector, MetricDefinition, vmware

TEMPERATURE = MetricDefinition(
    key="example.host.temperature_c",
    display_name="Host temperature",
    unit="C",
    entity_type="HostSystem",
)


class TemperatureCollector(MetricCollector):
    id = "example.host.temperature"
    display_name = "Example Host Temperature"
    version = "0.1.0"
    metrics = (TEMPERATURE,)

    def sample(self, si, context):
        for host in vmware.iter_hosts(si):
            yield TEMPERATURE.at(
                entity_moid=vmware.moid(host),
                entity_name=host.name,
                value=read_temperature(host),
            )


build_collector = TemperatureCollector   # クラス自体が引数なしファクトリになる
```

```toml
[project]
dependencies = ["vcenter-event-assistant-plugin-api>=1.1,<2"]

# entry point の名前は CollectorManifest.id と一致させる。
[project.entry-points."vcenter_event_assistant.collectors"]
"example.host.temperature" = "example_temperature_collector:build_collector"
```

## 2 つのバージョン

| | 意味 | 上げるとき |
|---|---|---|
| `__version__` | 配布パッケージの SemVer | 後方互換な追加で minor |
| `PLUGIN_API_VERSION` | 契約世代。アプリが `manifest.api_version` と突き合わせる | **契約を壊すときだけ** |

アプリは `api_version` が一致しないプラグインを `failed` として拒否する。
`PLUGIN_API_VERSION` を上げると既存の全プラグインが動かなくなる。

## 主なモジュール

| モジュール | 用途 |
|---|---|
| （ルート） | `CollectorPlugin` / `CollectorManifest` / `CollectionBatch` などの契約 |
| `collector` | `MetricCollector` / `EventCollector`。宣言的な基底クラス |
| `cursors` | `TimestampCursor`。空バッチでも前進し、境界を取りこぼさない |
| `config` | 設定値の型を吸収する（環境変数由来は常に `str`） |
| `validation` | アプリと**同一**の検査規則。`check_batch()` を自分のテストで呼べる |
| `limits` | DB の列長と `vmware_key` の範囲、安定キー生成 |
| `timeutils` | `now_utc()` / `ensure_aware()` / `to_utc()` |
| `blocking` | `run_blocking()`。キャンセル安全なスレッド退避 |
| `logs` | `get_plugin_logger()`。ロガー名の規約 |
| `vmware` | pyVmomi でのインベントリ走査（pyVmomi は遅延 import） |
| `testing` | アプリを起動せずにコレクタを回すテストハーネス |
| `scaffold` | そのまま動くプロジェクトを生成する CLI |

`vmware` ヘルパをアプリの外で動かすときだけ pyVmomi が要る。

```bash
pip install "vcenter-event-assistant-plugin-api[vmware]"
```

実行時はアプリ本体の依存としてワーカーの `sys.path` に見えているので、プラグイン側の
`dependencies` に加える必要はない。

## ドキュメント

- [コレクタプラグインの開発](https://github.com/t-m0riyama/vcenter-event-assistant/blob/main/docs/collector-plugin-authoring.md)
  — 実装・テスト・落とし穴・配布
- [コレクタプラグイン](https://github.com/t-m0riyama/vcenter-event-assistant/blob/main/docs/collector-plugins.md)
  — 設定・管理画面・トラブルシュート（運用側）
- [CHANGELOG](https://github.com/t-m0riyama/vcenter-event-assistant/blob/main/packages/plugin-api/CHANGELOG.md)

## ライセンス

Apache License 2.0
