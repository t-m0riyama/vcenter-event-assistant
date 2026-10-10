# プラグインの共通導入仕様（plugin-api 1.4）

プラグインは本体をimportせず、設定フォームと読取専用の診断を宣言できます。
`CollectorManifest.configuration_schema` と `setup_actions` は末尾の任意項目です。
`CollectorBase`・`MetricCollector`・`EventCollector`のサブクラスでは同名のクラス属性を宣言します。
既存の位置引数、`PLUGIN_API_VERSION=1`、宣言しないプラグインの動作は維持します。

## 設定の宣言

JSON Schemaの対応範囲は、object、array、string、number、integer、boolean、enum、required、
additionalProperties（真偽値）、default、title、description、数値上下限、文字列長、配列長です。
外部の `$ref` や任意HTMLは使用できません。未対応の定義は導入画面に理由を表示し、収集自体は停止しません。
JSONとしてエンコードできる辞書を使用し、秘密情報をdefault値や説明文へ含めないでください。

本体の入力部品はプロパティの `x-vea-widget` で指定します。

- `vcenter`：登録済みの有効なvCenterを名前で選択します。値は本体が管理するIDです。
- `esxi-host`：vCenter配下のESXi候補とvCenter自身を表示します。ホスト名の手入力も可能です。
  同じオブジェクトのvCenter項目を `x-vea-vcenter-field` で指定します。
- `ssh-connection`：共通のSSH接続先を選択し、鍵登録・ホスト鍵承認へ進めます。
  ホスト名の入力補助項目を `x-vea-host-field` で指定できます。

オブジェクトの `x-vea-ssh-connection` にSSH接続参照のプロパティ名を指定すると、
実行時だけ、そのオブジェクトにhost、port、username、private_key_file、known_hosts_fileを解決します。
保存されるのは参照IDのみです。鍵ファイルの寿命はワーカー要求の終了までで、保持して次回再利用してはいけません。
接続先IDなどの非表示項目には `x-vea-generated-id: true` を指定できます。フォーム追加時に生成し、編集中は維持します。

## 導入アクション

`SetupAction(id, title, required_for_enable=False)` をmanifestに追加し、任意の
`async setup(context: CollectionContext, action: str) -> SetupResult` を実装します。
戻り値は `SetupCheck` の検査項目、警告、辞書形式の表示用サンプルです。
すべてプレーンテキストとして表示されます。サンプルは全対象を通して20件、API結果は256KiBに制限します。

`required_for_enable=True` のアクションは、現在の設定とSSH接続先の承認内容で成功しないと適用できません。
設定や接続情報の変更、プラグインのバージョン変更で以前の結果は利用できなくなります。
宣言したアクションだけを呼び出し、外部プラグインではワーカー内で実行します。
contextのcursorはNoneです。診断はデータ保存やカーソル更新を行わず、通常収集の実行記録も更新しません。
秘密鍵、APIパスワード、ファイルの機密内容を検査結果・例外メッセージ・ログへ含めないでください。

[温度メトリクスのサンプル](../../examples/example-temperature-collector/src/example_temperature_collector/__init__.py)
はSSHを使わない共通フォームと合成値の試し読みを示します。
[リモートログ](../../packages/remote-log-collector/src/vea_remote_log_collector/__init__.py)
は配列、vCenter・ESXi候補、SSH参照、必須の接続テストを示します。

## 本体APIと設定適用

管理機能を有効にし、外部認証でアクセスを制限した環境で利用します。

- `GET /api/plugins/collectors/{id}/configuration`：定義、環境変数による固定項目、下書き。
- `PUT /api/plugins/collectors/{id}/draft`：設定とrevisionを送信して下書き保存。
- `POST .../draft/import`：現在の設定を下書きへ明示的に読み込む。秘密鍵は取り込まない。
- `POST .../draft/validate`：設定型、vCenter、承認済みSSH参照の検証。
- `POST .../draft/actions/{action}`：revisionを指定して診断を実行。
- `POST .../draft/apply`：revisionとテスト結果を確認し、候補レジストリを起動して適用。
- `GET /api/plugins/vcenters/{id}/hosts`：ESXi候補の取得。
- `/api/plugins/ssh/credentials`：鍵の一覧・生成・登録。`/{id}/public-key`で公開鍵取得、`DELETE /{id}`で未使用鍵削除。
- `/api/plugins/ssh/connections`：接続先の一覧・登録。`PUT /{id}`で未使用接続先の編集、
  `POST /{id}/host-key`で認証前の鍵取得、`POST /{id}/approve`で指紋とrevisionを照合して承認。

下書きは稼働中の設定から分離します。適用済みのフォーム設定はTOMLのconfig全体を置き換え、
環境変数がさらに優先されます。既存の手動設定の優先順位とマージ方式は維持します。
収集中または有効な保存済み設定が使うSSH接続先は直接変更せず、新しい接続先を作って再テスト・適用します。
既存の第三者パッケージ導入は依存関係を自動取得する方式へ変更していません。
