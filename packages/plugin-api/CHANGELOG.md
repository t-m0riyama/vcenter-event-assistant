# Changelog

このパッケージのバージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従う。

## バージョニング規約

**2 つのバージョンを混同しないこと。**

- **パッケージの `__version__`（SemVer）**: 後方互換な追加で minor、契約の破壊的変更で
  major を上げる。プラグインは `vcenter-event-assistant-plugin-api>=1.1,<2` のように宣言する。
- **`PLUGIN_API_VERSION`（契約世代）**: アプリの `registry._validate_plugin` が
  `manifest.api_version` と突き合わせ、一致しないプラグインを
  `unsupported plugin API version` として `failed` にする。したがって
  **契約を壊すときだけ**上げる。ヘルパの追加で上げてはならない。上げた時点で
  既存の全プラグインが一斉に動かなくなる。

## [1.1.0]

契約（データクラスと `CollectorPlugin` Protocol）は変更していない。`PLUGIN_API_VERSION`
は `1` のままである。既存のプラグインは何も変えずに動く。

### Added

- `validation`: アプリと同一の検査規則。`check_batch()` / `check_manifest()` は問題を
  `Issue` の列として返し、`validate_batch()` / `validate_manifest()` は送出する。
  `severity` が `"error"` のものはアプリが実際に拒否する条件と一致する。`"warning"` は
  アプリは拒否しないが放置するとデータが静かに失われるもの（列長超過、`vmware_key` の
  32 bit 範囲外、バッチ内の重複排除キー衝突、空の `entity_moid`）。
- `limits`: DB の列長、`vmware_key` の範囲、`truncate()`、`stable_int63()` /
  `stable_int31()`。
- `timeutils`: `now_utc()` / `is_aware()` / `ensure_aware()` / `to_utc()`。
  `ensure_aware` は naive に付与するだけ、`to_utc` は aware も変換する。
- `blocking.run_blocking()`: キャンセルされてもスレッドと vCenter セッションを
  取り残さないスレッド退避。素の `asyncio.to_thread` の代わりに使う。
- `logs.get_plugin_logger()`: `VEA_COLLECTOR_WORKER_LOG_LEVEL` が効く名前空間の
  ロガーを返す。
- `MetricDefinition.at()`: 定義から `metric_key` / `entity_type` / `sampled_at` を
  補って `MetricSampleInput` を作る。メトリクスキーの二重記述と naive な datetime を
  同時に防ぐ。
- `py.typed`（型情報を配布する）、`__version__`、パッケージメタデータ一式。
- `__all__` に `ConnectionFactory` / `DataKind` / `SeriesMode` を追加（従来は定義済みだが
  未公開で、作者が自分の型注釈に使えなかった）。

### Notes

- `stable_int31()` は**推奨しない**。`vmware_key` の重複排除は
  `ON CONFLICT DO NOTHING` なので、31 bit 空間では約 4.6 万件で 50% の誕生日衝突が起き、
  衝突したイベントがエラーもログもなく捨てられる。情報源の自然キーを使うこと。

## [1.0.0]

### Added

- 初版。`CollectorPlugin` Protocol、`CollectorManifest`、`MetricDefinition`、
  `EventInput`、`MetricSampleInput`、`CollectionBatch`、`VCenterTarget`、
  `CollectionContext`、`ConnectionFactory`、`PLUGIN_API_VERSION`。
