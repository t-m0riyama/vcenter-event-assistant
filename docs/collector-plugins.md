# コレクタプラグイン

vCenter Event Assistant は、アプリケーションの起動時にコレクタプラグインを検出します。組み込み
コレクタと外部コレクタは、同じバージョン付きの契約を使用します。外部プラグインは信頼された
Python コードであり、アプリケーションと同じ権限で動作します。信頼できるパッケージのみを
インストールしてください。

## 設定

`VEA_COLLECTOR_CONFIG_FILE` に TOML ファイルを指定します。組み込みコレクタは既定で有効です。
外部コレクタは、テーブルで `enabled = true` を設定しない限り無効です。

```toml
[collectors."builtin.vcenter.events"]
enabled = true
interval_seconds = 120
timeout_seconds = 300

[collectors."example.host.temperature"]
enabled = true
interval_seconds = 300
timeout_seconds = 60

[collectors."example.host.temperature".config]
sensor = "system-board"
```

プラグイン固有の機密値は、そのプラグインが所有し文書化した環境変数から読み取るべきです。共通
設定と単純なプラグイン値は、`VEA_COLLECTOR__<正規化したプラグインID>__ENABLED`、
`__INTERVAL_SECONDS`、`__TIMEOUT_SECONDS`、`__<設定キー>` により TOML を上書きできます。
ID 中のドットとハイフンはアンダースコアになります。たとえば
`VEA_COLLECTOR__EXAMPLE_HOST_TEMPERATURE__SENSOR=cpu-package` は `config.sensor` を上書きします。
機密値を TOML ファイルに置いてはなりません。不正・欠落・非互換のプラグインは
`GET /api/plugins/collectors` で `failed` として表示されます。アプリケーションの起動は妨げません。

## 管理画面

**設定 > プラグイン**画面には、各 vCenter に対する実効の共通設定と最新の実行状況が表示されます。
任意のプラグイン設定値や機密値は一切公開されません。

`VEA_PLUGIN_MANAGEMENT_ENABLED=true` でない限り、この画面は参照専用です。管理を有効にすると、
コレクタの有効化・無効化、実行間隔とタイムアウトの変更、パッケージのインストールと
アンインストール、アプリケーションを再起動せずにレジストリをリロードすることもできます。

**プラグインのインストール、アンインストール、リロードは、実質的に任意コード実行です。**
本アプリケーションは独自の認証を持たないため、リバースプロキシが `/api/plugins` に対して認証を
強制している場合のみ管理を有効にしてください。この設定は既定で無効です。

## サンプルプラグイン

[`examples/example-temperature-collector/`](../examples/example-temperature-collector/) は実行可能な
サンプルです。最小構成のメトリクスコレクタと、ビルド・インストール・有効化・リロード・
アンインストールを網羅した README で構成されます。障害を注入することもできるため
(`EXAMPLE_COLLECTOR_FAULT=hang|crash|raise`)、後述のプロセス分離の挙動を端から端まで観察できます。
このパッケージは意図的に uv ワークスペースのメンバーに含めていないため、開発環境に誤って
インストールされることはありません。

## パッケージの entry point

プラグインは `vcenter-event-assistant-plugin-api` のみに依存し、引数なしのファクトリを公開します。

```toml
[project.entry-points."vcenter_event_assistant.collectors"]
temperature = "example_temperature:build_collector"
```

ファクトリは `CollectorPlugin` を実装したオブジェクトを返します。メトリクスキーはマニフェストで
宣言し、インストール済みの全コレクタのあいだで一意である必要があります。各バッチの検証、および
データベース書き込み、イベントスコアリング、重複処理、カーソルのコミットはアプリケーションが
担います。

## 設定の優先順位

実効値は次の順（上が最優先）で解決されます。

| 参照元 | 対象範囲 | 備考 |
|---|---|---|
| 環境変数 | `enabled`、`interval_seconds`、`timeout_seconds`、プラグイン値 | 常に優先されます。ここで固定されたフィールドは `env_locked_fields` として報告され、UI では読み取り専用として表示されます。 |
| データベース | `enabled`、`interval_seconds`、`timeout_seconds` | 管理画面から書き込まれます。`NULL` は「未設定」を意味し、より低い参照元に委ねます。 |
| TOML ファイル | すべて | `VEA_COLLECTOR_CONFIG_FILE`。 |
| マニフェストの既定値 | `default_interval_seconds` | プラグインが宣言します。 |

機密値は、そのプラグインが所有する環境変数に置きます。データベースや TOML ファイルには
保存されません。

## 動的インストール

`VEA_PLUGIN_DIR`（既定 `data/plugins`）を設定します。各配布物は `uv pip install --target` により
`<VEA_PLUGIN_DIR>/<配布物名>/<バージョン>/` へ分離してインストールされるため、アンインストールと
ロールバックはディレクトリの削除で済みます。パッケージのインストールは、管理画面から `.whl` または
`.tar.gz` をアップロードして行います。アップロードは `--no-index` で実行され、ネットワークへは
到達しません。

パッケージインデックスから名前でインストールするには `VEA_PLUGIN_ALLOW_INDEX_INSTALL=true` が
必要です（必要に応じて `VEA_PLUGIN_INDEX_URL` も）。サプライチェーンのリスクがあるため既定では
無効です。要求指定は `<名前>` または `<名前>==<バージョン>` に限定されます。

オフラインのアップロードでは、インデックスがなく依存を解決できないため、パッケージ単体を
インストールします（`--no-index --no-deps`）。これは、`vcenter-event-assistant-plugin-api` を正しく
宣言したプラグインがそもそもインストールできる理由でもあります。このパッケージは
アプリケーションの必須依存であり、ワーカーの `sys.path` 上に既に見えているため、2 つ目のコピーは
不要であり、バージョン不整合のリスクだけをもたらします。*それ以外*の依存が必要なプラグインは、
インデックス経由でインストールするか、依存を同梱する必要があります。そうでない場合、後述の
インストール直後の検証が `ModuleNotFoundError` で失敗し、インストールはロールバックされます。

インストール後、パッケージは分離されたワーカー内で検証されます。`vcenter_event_assistant.collectors`
の entry point を提供しない場合、または entry point の読み込みに失敗した場合、インストール
ディレクトリは削除され、何も登録されません。新しくインストールされたコレクタは `disabled` として
現れます。有効化してから**変更を反映**を押して適用してください。

コンテナでは `VEA_PLUGIN_DIR` を永続ボリュームにマウントしてください。そうしないと、コンテナを
入れ替えたときにインストール済みプラグインが失われます。`uv` バイナリがイメージ内に存在する
必要があります（既に含まれています）。

## ホットリロード

`POST /api/plugins/collectors/reload`（**変更を反映**ボタン）は、レジストリを再構築し、新しい
イミュータブルなスナップショットをアトミックに有効化し、スケジューラのコレクタジョブを
再調整（追加・削除・再スケジュール）したうえで、はじめて前世代をドレインして停止します。
プロセスの再起動は不要です。画面に表示されるレジストリ世代は、リロードごとに増加します。

## プロセス分離

外部コレクタは、プラグインごとの専用ワーカープロセスで動作します。ワーカーはアプリケーション
自身のインタプリタで起動され、プラグインのインストールディレクトリは `sys.path` の末尾に
追加されます（したがってアプリケーションの依存がプラグイン同梱のものより優先されます）。
組み込みコレクタは引き続きインプロセスで動作します。

vCenter への接続はワーカー側でアプリケーションが開き、プラグインには
`open_vcenter_connection` ファクトリのみを渡すため、`CollectorPlugin` の契約は変わりません。
`timeout_seconds` を超えたプラグインはワーカーが kill され、ワーカーをクラッシュさせた
プラグインは、アプリケーションや他のプラグインに影響を与えることなく `failed` として
報告されます。

これによりクラッシュ、ハング、依存の衝突が分離されます。ただし悪意あるコードに対する
サンドボックスでは**ありません**。プラグインは、そのワーカーに渡された認証情報とワーカー
プロセスを共有します。信頼できるパッケージのみをインストールしてください。

## トラブルシュート

### ログの出どころ

ワーカーのログはワーカープロセスの **stderr** に出ます。stderr は親プロセスへ継承される
ので、アプリのログをそのまま見れば含まれています。ワーカー由来の行には
`[collector-worker <pid>]` が付きます。プラグイン 1 つにつき 1 プロセスなので、pid で
区別できます。

ワーカーの **stdout は JSON Lines プロトコル専用**です。プラグインの `print()` は起動
直後に stderr へ振り替えられるためプロトコルは壊れませんが、プラグインからの出力は
`print` ではなく `logging` を使ってください。ロガー名を
`vcenter_event_assistant.plugins.external.<プラグインID>` 配下にしておくと、下記の環境
変数で外部プラグインのログだけを詳細化できます。

`VEA_COLLECTOR_WORKER_LOG_LEVEL` でワーカーのログレベルを指定します。未設定時は
`LOG_LEVEL` を継承します。アプリ全体を `DEBUG` にせず、外部プラグインのログだけを詳細に
したいときに使います。ワーカーはログファイルを開きません（親と同じファイルをローテート
すると競合して親のログが失われるため）。永続化は親のプロセス管理に委ねます。

### `error_message` に何が出るか

`GET /api/plugins/collectors` と管理画面の実行状況に出る `error_message` は、既定では
**例外の型名と定型句だけ**です。例外文言は認証情報やサーバの応答本文を含みうるため、
そのまま外へ出しません。

例外的に、メッセージが import 名・entry point 名・設定キー名からしか生成されない型
（`ImportError` 系、`LookupError`、`NotImplementedError`）に限り、メッセージも表示します。
`vim.fault.*`、`ssl.SSLError`、汎用の `RuntimeError` は対象外です。

**完全な情報は常にワーカーの stderr にあります。**

### よくある失敗

| 表示 | 意味 | 対処 |
|---|---|---|
| `ModuleNotFoundError: No module named '...'` | プラグインの依存が入っていない | アップロード導入は `--no-index --no-deps` なので依存は解決されません。インデックス経由の導入を許可するか、依存を同梱してください |
| `load failed: ...` | entry point の読み込みに失敗 | ワーカーの stderr にトレースバックが出ています |
| `TimeoutError: collector execution failed` | `timeout_seconds` を超過してワーカーを kill した | 実行間隔とタイムアウトを見直してください。ワーカーは次回実行で作り直されます |
| `ValueError: collector execution failed` | バッチ検証で拒否された（naive datetime、未宣言のメトリクスキー、非有限値、宣言していない `data_kinds`） | ワーカーの stderr にどの検証に落ちたかが出ています |
| `configured plugin is not installed` | TOML に書いたプラグイン ID に対応する配布物がない | ID の綴りとインストール済み一覧を確認してください |
