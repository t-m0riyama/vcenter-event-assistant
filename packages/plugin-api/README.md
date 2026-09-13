# vcenter-event-assistant-plugin-api

[vCenter Event Assistant](https://github.com/t-m0riyama/vcenter-event-assistant) の
コレクタプラグインを書くための契約とヘルパである。**依存パッケージを持たない。**

プラグインはこのパッケージだけに依存する。アプリ本体（`vcenter_event_assistant`）を
import してはならない。

```toml
[project]
dependencies = ["vcenter-event-assistant-plugin-api>=1.1,<2"]

[project.entry-points."vcenter_event_assistant.collectors"]
"example.host.temperature" = "example_temperature_collector:build_collector"
```

entry point の名前は `CollectorManifest.id` と一致させる。

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
| `validation` | アプリと**同一**の検査規則。`check_batch()` を自分のテストで呼べる |
| `limits` | DB の列長と `vmware_key` の範囲、安定キー生成 |
| `timeutils` | `now_utc()` / `ensure_aware()` / `to_utc()` |
| `blocking` | `run_blocking()`。キャンセル安全なスレッド退避 |
| `logs` | `get_plugin_logger()`。ロガー名の規約 |

詳細は
[docs/collector-plugins.md](https://github.com/t-m0riyama/vcenter-event-assistant/blob/main/docs/collector-plugins.md)
を参照。

## ライセンス

Apache License 2.0
