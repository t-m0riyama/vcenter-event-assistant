# コレクタプラグイン

本書は設定と内部挙動のリファレンスです。画面の見方や導入手順から知りたい場合は
[プラグインの使い方（利用者向け）](user-guides/plugins.md)、プラグインを自作する場合は
[コレクタプラグインの開発](collector-plugin-authoring.md) を参照してください。

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

プラグイン固有の機密値は、そのプラグインが所有し文書化した環境変数から読み取るべきです。ワーカーには
許可した環境変数しか渡らないので、その変数名を `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH` に書きます（下の
「プロセス分離」）。共通
設定と単純なプラグイン値は、`VEA_COLLECTOR__<正規化したプラグインID>__ENABLED`、
`__INTERVAL_SECONDS`、`__TIMEOUT_SECONDS`、`__<設定キー>` により TOML を上書きできます。
ID 中のドットとハイフンはアンダースコアになります。たとえば
`VEA_COLLECTOR__EXAMPLE_HOST_TEMPERATURE__SENSOR=cpu-package` は `config.sensor` を上書きします。
機密値を TOML ファイルに置いてはなりません。不正・欠落・非互換のプラグインは
`GET /api/plugins/collectors` で `failed` として表示されます。アプリケーションの起動は妨げません。

## 管理画面

**設定 > プラグイン**画面には、各 vCenter に対する実効の共通設定と最新の実行状況が表示されます。
任意のプラグイン設定値や機密値は一切公開されません。行を開くと、マニフェストの
`description`（そのコレクタが何を集めるかの説明）も表示されます。

`VEA_PLUGIN_MANAGEMENT_ENABLED=true` でない限り、この画面は参照専用です。管理を有効にすると、
コレクタの有効化・無効化、実行間隔とタイムアウトの変更、パッケージのインストールと
アンインストール、アプリケーションを再起動せずにレジストリをリロードすることもできます。

**プラグインのインストール、アンインストール、リロードは、実質的に任意コード実行です。**
管理系の API は admin ロールのユーザーだけが呼べます。admin ロールを信頼できる利用者だけに
付与している場合のみ管理を有効にしてください。この設定は既定で無効です。

## プラグインを書く

プラグインの作り方は [コレクタプラグインの開発](collector-plugin-authoring.md) を参照して
ください。ひな形の生成、実装すべきメソッド、ヘルパ、テストの書き方、落とし穴の一覧が
まとまっています。

サンプルは
[`examples/example-temperature-collector/`](../examples/example-temperature-collector/)（メトリクス）と
[`examples/example-event-collector/`](../examples/example-event-collector/)（イベント）です。
どちらもアプリを起動せずに `pytest` だけでテストが通ります。

## 設定の優先順位

実効値は次の順（上が最優先）で解決されます。

| 参照元 | 対象範囲 | 備考 |
|---|---|---|
| 環境変数 | `enabled`、`interval_seconds`、`timeout_seconds`、プラグイン値 | 常に優先されます。ここで固定されたフィールドは `env_locked_fields` として報告され、UI では読み取り専用として表示されます。 |
| データベース | `enabled`、`interval_seconds`、`timeout_seconds` | 管理画面から書き込まれます。`NULL` は「未設定」を意味し、より低い参照元に委ねます。 |
| TOML ファイル | すべて | `VEA_COLLECTOR_CONFIG_FILE`。 |
| マニフェストの既定値 | `default_interval_seconds` | プラグインが宣言します。 |

機密値は、そのプラグインが所有する環境変数に置き、その名前を `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH` に
書きます。データベースや TOML ファイルには保存されません。

## 動的インストール

`VEA_PLUGIN_DIR`（既定 `data/plugins`）を設定します。各配布物は `uv pip install --target` により
`<VEA_PLUGIN_DIR>/<配布物名>/<バージョン>/` へ分離してインストールされるため、アンインストールと
ロールバックはディレクトリの削除で済みます。パッケージのインストールは、管理画面から `.whl` または
`.tar.gz` をアップロードして行います。アップロードは `--no-index` で実行され、ネットワークへは
到達しません。

パッケージインデックスから名前でインストールするには `VEA_PLUGIN_ALLOW_INDEX_INSTALL=true` が
必要です（必要に応じて `VEA_PLUGIN_INDEX_URL` も）。サプライチェーンのリスクがあるため既定では
無効です。要求指定は `<名前>` または `<名前>==<バージョン>` に限定されます。

インデックスは `VEA_PLUGIN_INDEX_URL` で指定します。インストーラ（uv）には、インデックスの URL や
資格情報を表す環境変数（`UV_INDEX_URL`・`UV_DEFAULT_INDEX`・`UV_INDEX_<名前>_PASSWORD`・
`PIP_INDEX_URL` など）を渡しません。sdist のビルドのコード（`setup.py` など）が読めてしまうためです。
同じ理由で、`VEA_PLUGIN_INDEX_URL` かプロキシの環境変数（`HTTPS_PROXY` など）に資格情報
（`https://user:pass@...`）が含まれるときは `--no-build` で wheel だけを入れます。sdist しかないパッケージは、wheel を用意するかアップロードで入れてください。
インデックスからのインストールを許可しているときは、アップロードしたパッケージの依存も同じ
インデックスから解決します。ただし、資格情報があるときは、アップロードした sdist
（`.tar.gz`）はインデックスを使わずに入れます（`--no-index --no-deps`。ビルドのコードに資格情報を
渡さないため）。依存は解決されないので、依存のあるプラグインは wheel でアップロードしてください。

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

ワーカーとインストーラには、アプリの環境変数をそのまま渡しません。渡すのは次のものだけです。

- 実行環境: `PATH`・`HOME`・`LANG`・`LC_*`・`TZ`・`TMPDIR`・`SSL_CERT_FILE` などの証明書の場所・
  プロキシ（`HTTP(S)_PROXY`・`NO_PROXY`）。資格情報付きのプロキシ（`http://user:pass@proxy`）は、
  ワーカーには `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH` に書いたときだけ、インストーラには wheel だけを
  入れるとき（`--no-build`）だけ渡します
- ワーカーの設定: `LOG_LEVEL`・`VEA_COLLECTOR_WORKER_LOG_LEVEL`・`VCENTER_ALLOWED_HOST_SUFFIXES`。
  `.env` で指定した値も、アプリが読んだ値を渡します
- `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH`（カンマ区切り）に書いた名前の環境変数（ワーカーだけ）
- インストーラだけ: 資格情報を含まない uv の設定（`UV_CACHE_DIR`・`UV_NATIVE_TLS`・`UV_HTTP_TIMEOUT` など）

`VEA_SECRET_KEY`・`DATABASE_URL`・LLM や SMTP の資格情報は渡しません。ワーカーは `.env` も読みません。
ただしワーカーはアプリと同じ OS のユーザーで動くので、そのユーザーが読めるファイル（`.env`、
SQLite のデータベースファイルなど）は読めます。Linux では、アプリのプロセスを
`prctl(PR_SET_DUMPABLE, 0)` にして、ワーカーから `/proc/<アプリの pid>/environ` やメモリを読めない
ようにしています（`VEA_PROCESS_NON_DUMPABLE`、既定 `true`）。

**現在のバージョンの制約**: インストーラ（uv）が使う資格情報（`VEA_PLUGIN_INDEX_URL` の資格情報、
資格情報付きのプロキシ）は、インストールの間、uv のコマンドラインと環境変数に載ります。uv は
アプリと同じ OS のユーザーで動くので、そのとき既に動いているプラグインのワーカーは
`/proc/<uv の pid>/cmdline` や `/proc/<uv の pid>/environ` から読めます。`--no-build` で防げるのは、
インストールするパッケージ自身のビルドのコードからの読み取りだけです。同じユーザーで動かす限り、
根本的には防げません。資格情報の要らない社内ミラー（ネットワークや IP アドレスで接続元を制限する）を
使うことを勧めます。将来、インストーラやワーカーを別の OS のユーザーで動かすなどの分離を検討します。

**起動方法の注意**: `uv run vcenter-event-assistant` や、アプリと同じ OS のユーザーで動くプロセス管理
ツールから起動すると、起動した側のプロセスが、秘密の環境変数（`VEA_SECRET_KEY`・`DATABASE_URL`、
資格情報を含む `VEA_PLUGIN_INDEX_URL`・`HTTPS_PROXY`・`VCENTER_HTTP_PROXY` など）を持ったまま親として残ります。`prctl` で守れるのはアプリのプロセスだけなので、プラグインのワーカーは
`/proc/<親の pid>/environ` から読めます。本番では、アプリが起動した側のプロセスを置き換える形
（`exec`）で起動してください（例: `uv run` を使わず `exec .venv/bin/vcenter-event-assistant` で起動する。
対話シェルから `exec` を付けずに実行すると、シェルが親として残ります。Docker イメージはそうなっています）。この状態を見つけると、起動時に WARNING を出します
（`the parent process ... keeps secret environment variables`）。動き続けるプロセス管理ツールは、子の起動に
`exec` を使っても自分は残るので解決になりません。root で動く systemd など、アプリと別のユーザーで動かすか、
ツール自身に秘密の環境変数を持たせないでください。

この警告は変数の名前で判定する目安です。名前に `PASSWORD`・`API_KEY`・`SECRET`・`TOKEN` などを含む変数と、
名前の末尾が `PROXY`・`_URL`・`_URI`・`_ENDPOINT`・`_INDEX` で値に資格情報（`user:pass@`）を含む変数を
秘密とみなします（大文字と小文字は区別しません）。これ以外の名前の秘密は見つけられないので、警告が
出ないことは安全の保証になりません。本番は、警告の有無にかかわらず上の起動方法にしてください。

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

例外的に、メッセージがワーカー自身か import 機構からしか生成されない型に限り、メッセージも
表示します。具体的には `ImportError` 系（メッセージはモジュール名）、entry point が見つからない
場合、`NotImplementedError`、そしてバッチ・manifest の検証エラー（`BatchValidationError` /
`ManifestValidationError`。文言は静的なメッセージと、プラグインが宣言したメトリクスキーだけから
作られます）です。

`vim.fault.*`、`ssl.SSLError`、汎用の `RuntimeError` は対象外です。`KeyError` のように
**メッセージがデータそのものになる型**も対象外です（`KeyError` の文言は見つからなかった
キー自身なので、プラグインが秘密の値で辞書を引いていると、その値が表に出てしまいます）。

**完全な情報は常にワーカーの stderr にあります。**

### よくある失敗

| 表示 | 意味 | 対処 |
|---|---|---|
| `ModuleNotFoundError: No module named '...'` | プラグインの依存が入っていない | アップロード導入は `--no-index --no-deps` なので依存は解決されません。インデックス経由の導入を許可するか、依存を同梱してください |
| `load failed: ...` | entry point の読み込みに失敗 | ワーカーの stderr にトレースバックが出ています |
| `TimeoutError: collector execution failed` | `timeout_seconds` を超過してワーカーを kill した | 実行間隔とタイムアウトを見直してください。ワーカーは次回実行で作り直されます |
| `BatchValidationError: ...` | バッチ検証で拒否された。**どの規則に違反したかがそのまま出ます**（例: `metric sampled_at must be timezone-aware`、`undeclared metric key: example.host.humidity_pct`） | [コレクタプラグインの開発](collector-plugin-authoring.md#バッチが拒否される条件)を参照。拒否はバッチ丸ごとに及び、部分保存もカーソル前進も起こりません |
| `configured plugin is not installed` | TOML に書いたプラグイン ID に対応する配布物がない | ID の綴りとインストール済み一覧を確認してください |
