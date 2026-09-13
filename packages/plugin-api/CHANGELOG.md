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

- `collector`: 宣言的な基底クラス。`MetricCollector` / `EventCollector` を継承すると、
  実装するのは同期のメソッド 1 つ（`sample()` / `fetch()`）だけになる。マニフェストは
  クラス属性から組み立てられ、**クラス定義の時点で**検証される。接続の開閉、
  `run_blocking` でのスレッド退避、`mock_mode` の分岐、`CollectionBatch` の組み立て、
  カーソルの decode と前進は基底が引き受ける。`data_kinds` は基底クラスから導出される
  （書き忘れるとバッチが丸ごと拒否される宣言なので、手で書かせない）。
  既存の `manifest = CollectorManifest(...)` を明示するスタイルもそのまま動く。
- `cursors.TimestampCursor`: タイムスタンプ 1 つをカーソルとして扱う規則。
  取得範囲を既定 1 秒だけ戻して境界のイベントを取りこぼさず、**空のバッチでも必ず前進する**
  （前進しないと同じ範囲を永久に読み直す）。壊れたカーソルは初回として扱う。
- `config`: `get_str` / `get_int` / `get_float` / `get_bool` / `get_str_list` /
  `require_str`。環境変数由来の値は常に `str`、TOML 由来は TOML の型という非対称を吸収する。
  エラーメッセージにはキー名と型だけを含め、値は含めない。
- `validation`: アプリと同一の検査規則。`check_batch()` / `check_manifest()` は問題を
  `Issue` の列として返し、`validate_batch()` / `validate_manifest()` は送出する。
  `severity` が `"error"` のものはアプリが実際に拒否する条件と一致する。`"warning"` は
  アプリは拒否しないが放置するとデータが静かに失われるもの（列長超過、`vmware_key` の
  32 bit 範囲外、バッチ内の重複排除キー衝突、空の `entity_moid`）。
- `limits`: DB の列長、`vmware_key` の範囲、`truncate()`、`stable_int63()` /
  `stable_int31()`、`composite_entity_moid()` / `composite_entity_name()`
  （1 ホストが NIC やディスクごとに複数系列を持つ場合の複合 ID）。
- `vmware`: pyVmomi でのインベントリ走査。`container_view()` は例外時も含めて
  必ず `Destroy()` する。`iter_hosts()` は切断中のホストを既定で除き、
  `iter_datastores()` はアクセス不能なデータストアを除く。`moid()` が private な
  `_moId` への参照を 1 箇所に閉じる。型は **名前の文字列**で指定するので、
  プラグインは `from pyVmomi import vim` を書かなくてよい。
  **pyVmomi はモジュールの import 時には読み込まれない**（関数内で遅延 import する）
  ため、コアの依存ゼロは保たれている。アプリの外で使う場合のみ extra
  `vcenter-event-assistant-plugin-api[vmware]` が要る。
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
