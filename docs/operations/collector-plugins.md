# コレクタプラグイン

本書は設定と内部挙動のリファレンスです。画面の見方や導入手順から知りたい場合は
[プラグインの使い方（利用者向け）](../userguide/plugins.md)、プラグインを自作する場合は
[コレクタプラグインの開発](../development/collector-plugin-authoring.md) を参照してください。

vCenter Event Assistant は、アプリケーションの起動時にコレクタプラグインを検出します。組み込み
コレクタと外部コレクタは、同じバージョン付きの契約を使用します。外部プラグインは信頼された
Python コードであり、アプリケーションと同じ権限で動作します。信頼できるパッケージのみを
インストールしてください。

## 設定

`VEA_COLLECTOR_CONFIG_FILE` に TOML ファイルを指定します。組み込みコレクタは既定で有効です。
外部コレクタは、テーブルで `enabled = true` を設定しない限り無効です。

`builtin.vcenter.events` と `builtin.vcenter.tasks` の既定の実行間隔は
`EVENT_POLL_INTERVAL_SECONDS`（既定 120 秒）で決まります。個別に変更する場合は
各コレクタの `interval_seconds` を指定してください。完了したタスクの結果の取り込みを
止めるには、`builtin.vcenter.tasks` を無効にします。

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
「脅威モデル」）。共通設定と単純なプラグイン値は、`VEA_COLLECTOR_ID__<ID の UTF-8 バイト列を大文字16進表記>__<設定キー>`
で TOML と DB の設定を上書きできます。設定キーは従来と同じく、大文字と小文字を区別しません。
たとえば `example.host.temperature` の `config.sensor` を上書きする変数は次のように確認できます。

```sh
python3 -c 'print("VEA_COLLECTOR_ID__" + "example.host.temperature".encode().hex().upper() + "__SENSOR")'
```

旧形式の `VEA_COLLECTOR__<ドット・ハイフンをアンダースコアにした大文字のID>__<設定キー>`
も、一つのプラグインに対応する場合は使えます。同じ項目に新旧両方の指定があるときは新形式が優先されます。
複数のプラグインに対応する旧変数がある場合は、稼働中に読み込まれるプラグインを停止状態にし、導入で新たな衝突が生じる場合は公開を拒否します。
ログに出た旧変数を削除し、意図したプラグインの新形式の変数に置き換えてから再読み込みしてください。
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

プラグインの作り方は [コレクタプラグインの開発](../development/collector-plugin-authoring.md) を参照して
ください。ひな形の生成、実装すべきメソッド、ヘルパ、テストの書き方、落とし穴の一覧が
まとまっています。

サンプルは
[`examples/example-temperature-collector/`](../../examples/example-temperature-collector/)（メトリクス）と
[`examples/example-event-collector/`](../../examples/example-event-collector/)（イベント）です。
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

`VEA_PLUGIN_DIR`（既定 `data/plugins`。Docker イメージでは `/data/plugins`）を設定します。各配布物は `uv pip install --target` により
`<VEA_PLUGIN_DIR>/<配布物名>/<バージョン>/` へ分離してインストールされるため、アンインストールと
ロールバックはディレクトリの削除で済みます。パッケージのインストールは、管理画面から `.whl` または
`.tar.gz` をアップロードして行います。既定のアップロードでは uv に `--no-index --no-deps` を
指定します。

パッケージインデックスから名前でインストールするには `VEA_PLUGIN_ALLOW_INDEX_INSTALL=true` が
必要です（必要に応じて `VEA_PLUGIN_INDEX_URL` も）。サプライチェーンのリスクがあるため既定では
無効です。要求指定は `<名前>` または `<名前>==<バージョン>` に限定されます。

インデックスは `VEA_PLUGIN_INDEX_URL` で指定します。アプリの環境に設定された `UV_INDEX_URL`、
`UV_DEFAULT_INDEX`、`UV_INDEX_<名前>_PASSWORD`、`PIP_INDEX_URL` などは継承しません。
同じ理由で、`VEA_PLUGIN_INDEX_URL` かプロキシの環境変数（`HTTPS_PROXY` など）に資格情報
（`https://user:pass@...`）が含まれるときは `--no-build` で wheel だけを入れます。sdist しかないパッケージは、wheel を用意するかアップロードで入れてください。
インデックスからのインストールを許可しているときは、アップロードしたパッケージの依存も同じ
インデックスから解決します。ただし、資格情報があるときは、アップロードした sdist
（`.tar.gz`）はインデックスを使わずに入れます（`--no-index --no-deps`。ビルドのコードに資格情報を
渡さないため）。分離モードでビルド時に必要な依存を取得する場合は、資格情報不要のインデックスを
使えるよう構成するか、ビルド済み wheel を用意してください。

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

公式 Compose は `/data/plugins` に専用の永続ボリュームをマウントします。分離モードでは、
検証した配布物を世代別ディレクトリに保存し、アプリが管理する公開参照を切り替えます。
旧世代は稼働中のワーカーが使い終わるまで保持します。

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
サンドボックスでは**ありません**。何を守り、何を守れないかは次の「脅威モデル」を参照してください。

## 脅威モデル

### 公式 Compose と Linux の分離モード

アプリ、コレクタワーカー、wheel インストーラ、sdist ビルダーをそれぞれ別 UID で実行します。
公式 Compose ではさらに別の PID 名前空間とネットワークを使います。アプリとの制御通信は
役割ごとの Unix ソケットを通り、双方が相手の UID を確認します。ワーカーがマウントするのは
プラグイン専用ボリュームの読み取り専用マウントと自分のソケット領域です。アプリの SQLite
（WAL・SHM を含む）、ログ、設定ファイル、他の役割のソケットは共有しません。
アプリは、登録済み SSH 接続の秘密鍵と `known_hosts`、および `VCENTER_CA_BUNDLE` の内容を
認証済みソケットで渡します。ワーカーは要求ごとに読み取り専用の一時ファイルを作り、
要求が終わると削除します。vCenter 用 CA のマウント先は、既存のアプリ側の設定を使えます。

PostgreSQL は Compose の内部ネットワークに置き、ポートを公開しません。アプリの HTTP は
引き続きホストのループバックに公開します。公開ポートへの到達性は Docker Engine の直接
ルーティングとホスト側のフィルタリングにも依存します。プラグイン系ネットワークから
公開 HTTP への接続も禁止する場合は、ホスト側で該当する送信元からの接続を遮断し、
名前とコンテナ IP の両方で確認してください。 [Docker のポート公開とルーティング](https://docs.docker.com/engine/network/port-publishing/)

認証付きインデックスやプロキシの設定は、ビルドを禁止した wheel インストーラだけに渡します。
インデックスの URL は uv の子プロセス環境に渡し、uv の引数と生のエラー出力には載せません。
sdist は専用ビルダーで扱います。カスタムインデックスやプロキシをビルドにも使う場合は、URL
のパスやクエリも含めて資格情報がないことを確認し、
`VEA_PLUGIN_ALLOW_UNAUTHENTICATED_BUILD_ENDPOINTS=true` をアプリに設定します。
オフラインの sdist アップロードでは uv のインデックスと依存解決を無効にします。
`UV_OFFLINE` や `UV_HTTP_TIMEOUT` などの uv オプションは引き継ぎます。カスタムの
`SSL_CERT_FILE` や `SSL_CERT_DIR` は、uv を使うサービスで設定して読み取り専用でマウントします。
オフラインの sdist ビルドにビルド依存のキャッシュが必要な場合は、`plugin-builder` 専用の
`UV_CACHE_DIR` を用意します。インストーラやアプリのキャッシュとは別にしてください。

ワーカー間、ビルドジョブ間はそれぞれ同じ UID を共有します。コレクタには処理に必要な
vCenter の接続情報や明示的に許可した環境変数が渡ります。診断用の鍵はログ収集用とは別に登録します。
診断を有効にして実行すると、診断用の SSH 秘密鍵も、ワーカーサービスを経由して診断ワーカーにメモリで渡ります。
ビルドコードとコレクタは自分で外向きの接続を開けるため、送信先の制限が必要な環境では
ネットワーク側で設定してください。
各ジョブとワーカーセッションには子プロセスの監督プロセスがあり、別のプロセスグループに移った
子孫も終了時に回収します。同じ UID のコードが監督プロセスに干渉できるため、信頼できないコードの
実行が疑われる場合は該当するサービスを再起動してください。
信頼できるプラグインを選び、管理機能は必要なときだけ有効にしてください。

#### 既存 Compose の更新

アプリを停止して DB と既存の `vea_data` をバックアップし、利用中の DB に合った新しい
Compose テンプレートへ更新します。同じ Compose プロジェクト名で以下を実行してください。

```sh
docker compose build app
docker compose run --rm --no-deps plugin-migrate
docker compose up -d --no-build
```

サービスを指定して起動する場合は、プラグイン管理を使う環境では `plugin-installer` と
`plugin-builder` も指定してください。
ワーカー自身が使う `SSL_CERT_FILE`、`SSL_CERT_DIR`、`REQUESTS_CA_BUNDLE`、
`CURL_CA_BUNDLE`、`PYTHONPATH` は `plugin-worker` 側で設定し、必要なファイルだけを
ワーカーに読み取り専用でマウントしてください。アプリ側のパス設定は引き継ぎません。
旧設定で `private_key_file` と `known_hosts_file` を直接指定している場合は、管理画面で SSH 鍵と
接続先を登録し、ホスト鍵を承認してから収集対象の設定でその接続先を選択してください。設定ファイルで
管理している場合は、直接指定を削除し、対象の `ssh_connection_id` に登録した接続先の ID を指定します。
分離モードでは、直接指定が残っていると検証・設定適用・収集時に移行を求めるエラーが出ます。

移行サービスは旧 `/data/plugins` の公開済み配布物を、新しい `vea_plugins` にコピーします。
手動配置も対象です。配布物にシンボリックリンクや特殊ファイルがある場合は、内容を確認して
通常のファイルとディレクトリに直してから移行してください。中断した場合は移行コマンドを再実行できます。
旧ボリュームのコピーは残るため、ロールバック時は旧テンプレートで元の公開済みツリーを参照できます。移行後に行った
インストールや削除も戻す場合は、停止中に移行後のプラグインボリュームと台帳を併せて確認してください。

#### Docker なしの Linux

1. `app`、`worker`、`installer`、`builder` 用に専用の非 root UID を作ります。既定値は
   順に 1000、1001、1002、1003 です。別の UID を使う場合は全プロセスに
   `VEA_PLUGIN_APP_UID`、`VEA_PLUGIN_WORKER_UID`、`VEA_PLUGIN_INSTALLER_UID`、
   `VEA_PLUGIN_BUILDER_UID` を同じ値で設定します。
2. 同じバージョンのアプリ、Python、プラグイン API を読み取り専用の場所に置きます。
   DB の親ディレクトリ、ログ、`.env`、秘密を含む起動設定はアプリ UID だけに読み書きを許可します。
   新しいプラグイン領域はアプリ所有で、ワーカーには読み取りと通過だけを許可します。
   旧プラグインの移行または空の領域の初期化は、アプリ UID で次のコマンドを実行します。

   ```sh
   python -m vcenter_event_assistant.plugins.publication /path/to/old/plugins /path/to/new/plugins
   ```

3. `VEA_PLUGIN_SERVICE_SOCKET_DIR` に全プロセスが通過できる短い絶対パスを設定します。その直下に
   `worker`、`installer`、`builder` ディレクトリを作り、それぞれ該当する UID を所有者、
   アプリのプライマリグループをグループ、モードを `2710` とします。サービスはその中に
   モード `0660` の `service.sock` を作ります。
4. 各サービスを専用 UID で `python -m vcenter_event_assistant.plugins.service worker`、
   `installer`、`builder` として起動します。アプリとワーカーの `VEA_PLUGIN_DIR` には同じ絶対パスを
   設定します。インストーラとビルダーには uv を用意し、必要なら各サービスで `VEA_UV_BIN` を
   設定します。アプリの `.env` を各サービスへ読み込ませず、証明書などは必要な役割に個別に
   読み取り権限を与えます。ソケットができたらアプリを起動します。1 つのプラグイン領域を
   更新するアプリは 1 インスタンスにします。
5. UID の分離は同一ホスト上の TCP アクセスを制限しません。必要に応じてファイアウォールなどで
   アプリ・DB のリスナーへのアクセスを制限し、監視対象と配布先への接続を確認します。

### 分離を設定していない単体起動

プラグイン（と、インストール中に実行される sdist のビルドのコード）は、アプリと**同じ OS のユーザー**で
動きます。プロセスの分離は、ハング・クラッシュ・依存の衝突を閉じ込めるためのもので、セキュリティの
境界ではありません。以下の対策は、プラグインから見える秘密を減らし、本体を書き換えられないようにする
ものですが、悪意のあるプラグインを無害にはできません。**インストールするプラグインは信頼できるものだけに
し、管理機能（`VEA_PLUGIN_MANAGEMENT_ENABLED`）は必要なときだけ有効にしてください。**

### 守っているもの

**秘密の環境変数**: ワーカーとインストーラには、アプリの環境変数をそのまま渡しません。渡すのは次のものだけです。

- 実行環境: `PATH`・`HOME`・`LANG`・`LC_*`・`TZ`・`TMPDIR`・`SSL_CERT_FILE` などの証明書の場所・
  プロキシ（`HTTP(S)_PROXY`・`NO_PROXY`）。資格情報付きのプロキシ（`http://user:pass@proxy`）は、
  ワーカーには `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH` に書いたときだけ、インストーラには wheel だけを
  入れるとき（`--no-build`）だけ渡します
- ワーカーの設定: `LOG_LEVEL`・`VEA_COLLECTOR_WORKER_LOG_LEVEL`・`VCENTER_ALLOWED_HOST_SUFFIXES`。
  `.env` で指定した値も、アプリが読んだ値を渡します
- `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH`（カンマ区切り）に書いた名前の環境変数（ワーカーだけ）
- インストーラだけ: 資格情報を含まない uv の設定（`UV_CACHE_DIR`・`UV_NATIVE_TLS`・`UV_HTTP_TIMEOUT` など）

`VEA_SECRET_KEY`・`DATABASE_URL`・LLM や SMTP の資格情報は渡しません。ワーカーは `.env` も読みません。

**アプリのプロセス**: Linux では、アプリのプロセスを `prctl(PR_SET_DUMPABLE, 0)` にして、ワーカーから
`/proc/<アプリの pid>/environ` やメモリを読めないようにしています（`VEA_PROCESS_NON_DUMPABLE`、既定 `true`）。

**アプリのコード**: Docker イメージでは、アプリのコードと `.venv`（`/app`）は root の所有で、実行ユーザー
（`appuser`）は書き込めません。`appuser` が書けるのは `/data`（DB とプラグイン）と `/var/log/vea` だけです。
compose のテンプレートは、さらにルートファイルシステムを読み取り専用（`read_only: true`）にしています。
Docker を使わない場合は、アプリのインストール先をアプリを動かすユーザーが書けないようにしてください。

### 守れないもの

**同じユーザーが読み書きできるファイル**: プラグインは、アプリのユーザーが読み書きできるファイルを
直接扱えます。SQLite のデータベースファイル（Docker では `/data` の下）、`.env`、他のプラグインの
インストールディレクトリ（`VEA_PLUGIN_DIR`）などです。SQLite の DB の中身は読み書きできます。DB の中の
パスワードや鍵は `VEA_SECRET_KEY` を設定していれば暗号化されていて、鍵はワーカーに渡さないので復号できません。
ただし鍵を同じユーザーが読めるファイル（`.env` など）に置いていると読まれます。Docker の compose のテンプレートは
`.env` を環境変数としてコンテナに渡すので、コンテナの中にファイルは残りません。PostgreSQL なら、資格情報を
渡さない限りプラグインは DB に入れません。

**インストール中の uv の資格情報**: インストーラ（uv）が使う資格情報（`VEA_PLUGIN_INDEX_URL` の資格情報、
資格情報付きのプロキシ）は、インストールの間、uv のコマンドラインと環境変数に載ります。uv は
アプリと同じ OS のユーザーで動くので、そのとき既に動いているプラグインのワーカーは
`/proc/<uv の pid>/cmdline` や `/proc/<uv の pid>/environ` から読めます。`--no-build` で防げるのは、
インストールするパッケージ自身のビルドのコードからの読み取りだけです。同じユーザーで動かす限り、
根本的には防げません。資格情報の要らない社内ミラー（ネットワークや IP アドレスで接続元を制限する）を
使うことを勧めます。

**起動した親プロセスの環境変数**: `uv run vcenter-event-assistant` や、アプリと同じ OS のユーザーで動くプロセス管理
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

**プラグインが自分で開く接続**: プラグインが自分で開く SSH や HTTP の接続の宛先は、アプリからは
制限できません。同梱のリモートログのプラグインは、接続の直前に名前解決して検証した IP に接続します
（ループバック・リンクローカル（メタデータ）・マルチキャスト・予約済み・未指定のアドレスには接続しない）。
接続先の名前を受け取るプラグインは、plugin-api の `network.resolve_ssh_address` で同じように検証し、
返った IP に接続してください（名前のまま接続すると、検証の後にもう一度名前解決が起きます）。

## トラブルシュート

### ログの出どころ

ワーカーのログはワーカープロセスの **stderr** に出ます。公式 Compose では
`docker compose logs plugin-worker` で確認できます。分離を設定していない単体起動の
ワーカーログはアプリのログに含まれます。ワーカー由来の行には
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
| `BatchValidationError: ...` | バッチ検証で拒否された。**どの規則に違反したかがそのまま出ます**（例: `metric sampled_at must be timezone-aware`、`undeclared metric key: example.host.humidity_pct`） | [コレクタプラグインの開発](../development/collector-plugin-authoring.md#バッチが拒否される条件)を参照。拒否はバッチ丸ごとに及び、部分保存もカーソル前進も起こりません |
| `configured plugin is not installed` | TOML に書いたプラグイン ID に対応する配布物がない | ID の綴りとインストール済み一覧を確認してください |
