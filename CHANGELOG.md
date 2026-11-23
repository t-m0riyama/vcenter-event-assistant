# 変更履歴

このファイルには、リリースごとの主な変更と、更新するときの注意を書く。版は [Semantic Versioning](https://semver.org/lang/ja/) に従う（1.0.0 より前は、互換性のない変更でも minor を上げる）。

同梱のパッケージの変更は、それぞれの CHANGELOG を参照する（[plugin-api](packages/plugin-api/CHANGELOG.md)）。

## 未リリース

### 更新の前に（互換性のない変更）

- **イベントの API 応答とイベントタブの CSV に主な対象の `entity_moid` を加えた**（Issue #347）。CSV では `entity_type` の直後に列が増えるため、列の位置で読んでいるスクリプトは直す必要がある
- **イベントに主な対象の名前と種別を入れるようにした**（Issue #347）。ホストの接続切れなどのイベントに対象の名前が入り、`entity_type` は `HostSystem` や `VirtualMachine` の形になる
  - 保存済みの行は更新しない。保持期間（`event_retention_days`、既定 7 日）が過ぎるまでは、空欄や引数の型名が入った古い行と新しい行が混ざる
- **`EventEx` と `ExtendedEvent` のイベント種別に `eventTypeId` を使うようにした**（Issue #346）。前後の空白を除いて空か 512 文字を超える場合は、クラス名を使う
  - `vim.event.EventEx` と `vim.event.ExtendedEvent` に設定したスコアルールとガイドは、それぞれのクラス名で保存した古い行と、`eventTypeId` が空などでクラス名を使う新しい行にだけ当たる。`ExtendedEvent` は `eventTypeId` が必須なので、ほぼすべてが新しい種別になる。ID で取り込まれるイベントに適用するには、`esx.problem.storage.apd.start` などの ID で設定し直す。スコアルールは種別の完全一致で適用する
  - イベントスコアのアラートは種別を状態のキー（`context_key`）にする。これまでクラス名ごとに 1 件にまとまっていたアラートの状態と再通知の間隔は `eventTypeId` ごとに分かれるため、更新直後から通知が増えることがある
  - `vim.event.EventEx` と `vim.event.ExtendedEvent` で発火中のイベントスコアのアラートは自動で解消されないため、手で解消する
  - 保存済みの古い行は `event_retention_days`（既定 7 日）が過ぎると消える
- **新しく取り込む 5 種別のイベントに、要注目スコアの種別加点（+40）が付くようにした**（Issue #350）。対象は `vim.event.VmFailedToPowerOnEvent`、`vim.event.VmFailedToStandbyGuestEvent`、`vim.event.VmFailedToSuspendEvent`、`vim.event.HostConnectionLostEvent`、`vim.event.DatastoreRemovedOnHostEvent`。vSphere API に存在しない `HostNotRespondingEvent` は対象から外した
  - この加点だけで要注意（40 点以上）になり、概要・ダイジェストの要注意件数に入り、概要タブのアテンションドットの対象になる。WEB 調査のスコア条件（`research_event_score_threshold`、既定 40）も満たすため、調査件数が増えることがある（1 サイクルの上限は `research_max_per_cycle`）
  - 取り込み時に重大度が付かない 5 種別は、スコアルールの加算が 0 なら、警告語の有無に応じて 40 点か 50 点になり、イベントスコアのアラートの既定の閾値（60 点）には届かない。閾値が 40 点以下のときや、警告語を含むイベントで閾値が 50 点以下のときは、通知が増えることがある
  - 更新時に保存済みのスコアとタグは変わらず、古い行は保持期間（`event_retention_days`、既定 7 日）が過ぎると消える。それまでは、概要の「種別上位」とダイジェストの種別表がその都度計算する最大スコアと、イベント一覧が表示する保存済みのスコアが食い違うことがある
  - すぐに揃えたいときは、対象の種別のスコアルールを保存する。ルールが無い種別には加算 0 のルールを追加する（追加後に削除してもよい）。各ルールの操作はその種別の行を、スコアルールの JSON インポートは全イベント行を再計算する。再計算するとスコアもタグも現在の採点方法に揃う。インポートは 1 回の要求で全行を読み込むため、行が多い環境では時間がかかる
- アラートルールを更新する `PATCH /api/alerts/rules/{id}` には、一覧などで取得した `revision` が必要になった（Issue #279）。直接呼び出すスクリプトは本文に `revision` を含める。複数台で運用する場合は旧バックエンドを停止し、全台を更新してから書き込みを再開する。 [API の仕様](docs/development/backend.md#24-ルールガイドアラート)
- ローカルログインを無効にすると、ローカルユーザーの既存セッションも失効する（Issue #292）。複数台で運用する場合は旧設定のインスタンスを停止してから切替を完了する。[ディレクトリ認証ガイド](docs/userguide/directory-auth.md#11-ディレクトリだけで運用する)
- 旧形式のプラグイン用環境変数が複数のプラグインに対応する場合は、対象のプラグインが起動しない（Issue #299）。起動ログに出る変数を一意な新形式に置き換える。[移行方法](docs/operations/collector-plugins.md)
- SSH の接続先にはスコープ指定のない IPv6 アドレスか DNS 名を使う（Issue #294）。既存設定でスコープ付きリテラルを指定している場合は接続先を更新する。
- **公式 Compose で、アプリ、プラグインワーカー、wheel インストーラ、sdist ビルダーを別の非 root ユーザーで実行する。** 既存環境ではプラグインを専用ボリュームへ移行する（Issue #274）。[移行手順と脅威モデル](docs/operations/collector-plugins.md#脅威モデル)
- **ディスク I/O の合計の指標名が、`host.disk.usage_pct` から `host.disk.usage_kbps` に変わった**（Issue #316）。値は vSphere の `disk.usage`（KB/s）で、以前から % ではなかった。集める値は変わらない
  - 保存済みのサンプル・アラートルール・スナップショットは、起動時のマイグレーション（`b5c6d7e8f9a0`）が新しい名前に付け替える。サンプルが多い環境では、付け替えが終わるまで起動に時間がかかる（[バックエンド運用ガイドの 5.4](docs/operations/backend-operations.md#54-索引を足すマイグレーションの所要時間)）
  - 手元に残したアラートルールの JSON に古い名前があれば、取り込む前に `metric_key` を直す。古い名前のまま取り込んだルールは発火しない
  - メトリクスの API を `metric_key=host.disk.usage_pct` で呼んでいるスクリプトは、新しい名前に直す
- **`POST /api/incident-timeline` を消した**（Issue #325）。画面からは使っていなかった
  - この API を直接呼んでいるスクリプトは、`POST /api/incident-timeline/view` に移す。応答の形は違う（時間バケットごとの集計ではなく、個々の出来事の一覧）
  - 要求の項目も違う。`/view` は `include_period_metrics_*`・`alert_top_n`・`top_notable_min_score` を受け付けず、送ると 422 になる。重要度の下限は `min_score`、対象の種別は `sources` で指定する
  - 時間バケットごとの形が必要なら、同じ形の `incident_timeline` が `POST /api/chat/preview` の応答に入っている。ただし operator 以上の権限と `messages`（1 件以上）が要り、本番では `CHAT_PREVIEW_ENABLED=true` にしないと 404 になる
  - 保存済みのスナップショットはそのまま開ける
- **`POST /api/incident-timeline/snapshots/manual` の外側の `from` / `to` に、常に 90 日の上限を当てるようにした**（Issue #330）。今まで `view_request` か `build_request_payload` が 90 日以内なら、外側が 90 日を超えていても 201 で保存できていた。これからは 422 になる
  - 影響するのは、この API を直接呼んで、外側だけ 90 日を超える本文を送っているスクリプト
  - 外側の `from` / `to` を、`view_request` と同じ 90 日以内の期間にする
  - 画面は外側にも表示中の期間を送るので、画面からの保存には影響しない

### 追加

- タイムライン API のハイライトに、ホストの切断の繰り返しや APD のタイムアウトなど、組み込みの障害パターン 7 種類の検知結果を加えた。定義は `GET /api/event-patterns` で参照できる。
- 新しく取り込むイベントは、主な対象の moid を `events.entity_moid` に、すべての対象を `event_entities` に保存する（Issue #347）。対象を含まない旧プラグインのイベントや、保存済みイベントの列と子表は後から補完しない。
- タイムライン API で、vCenter と対象の `entity_moid` を指定して絞り込めるようにした。イベントの参照、「影響の大きい対象」、新形式のメトリクス通知履歴にも moid を返す。対象名を指定する `entity` の上限は 1024 文字に広げた（Issue #347）。
- タイムラインの「この対象で絞る」「影響の大きい対象」と他のタブの「タイムラインで見る」で、vCenter と moid が分かる対象を完全一致で絞り込むようにした。moid は URL にも入り、対象の欄を編集すると名前の部分一致に戻る（Issue #347）。

### 修正

- タイムラインの「影響の大きい対象」を vCenter と moid ごとに数えるようにした。同名の別の対象を分け、名前を変えた対象は最新の名前で 1 つにまとめる（Issue #347）。
- タイムラインでイベントをまとめるキーに moid を加え、同じ名前で moid が異なる対象の連続したイベントは別の行にしたため、`entity_moid` を指定しない要求でも `items`、`total_items`、各行の `count` が変わることがある（Issue #347）。
- チャットの期間メトリクスやダイジェストの上位ホストの moid を、LLM への送信前に匿名化するようにした。会話やイベント CSV などのテキスト添付、イベントのメッセージ、ダイジェストの本文に現れる `vm-123` や `host-45` も同じ仕組みで置き換える。テキスト添付のファイル名も本文と同じ規則で匿名化する
- アラートルールを別タブや別ユーザー、JSON インポートが変更した後、古い画面から保存しても上書きされなくなった（Issue #279）。変更を検出した行から「編集を破棄して読み直す」を選べる。
- 保存済みスナップショットの `build_request_payload.vcenter_id` が RFC 形式以外の UUID でも、画面で一覧・詳細・保存直後の応答を読めるようにした。既存の行をそのまま読め、マイグレーションは不要（Issue #341）
- チャットで、ディスクとネットワークの指標（KB/s）に % の閾値を当てていたのをやめた。この 2 つはインシデントタイムラインの項目にせず、画面の「Disk 閾値（%）」「Network 閾値（%）」を外した。バケット平均は今までどおり LLM に渡る（Issue #316、PR #322）
- グラフ画面で vCenter を「全て」にしたとき、SQLite で期間に関係なく指標の全サンプルを読んでいたのを直した。登録済みの vCenter の id を並べて絞り、索引を使えるようにした。24 時間の表示では、件数と一覧の合計が約 20 秒から約 0.6 秒になる。PostgreSQL は変わらない（Issue #324）。新しい SQLite（3.51.0 以降で確認）でも、統計が無いときにこの索引を使うよう、`INDEXED BY` で固定した（Issue #334）
- `POST /api/incident-timeline/snapshots/manual` が、外側の `from` / `to` が 90 日を超えて `view_request` も `build_request_payload` も無いときに 500 を返していたのを、422 にした。`from` と `to` の片方だけにタイムゾーンが無いときも 500 を返していたが、タイムゾーンの無い値を UTC とみなして受け付けるようにした。期間の `from` / `to` に、UTC に直すと日時の範囲を外れる値（`0001-01-01T00:00:00+01:00` など）を送ったときも、500 ではなく 422 にした。タイムラインとチャットの要求の `from` / `to` は UTC に揃えて保存し、保存済みのスナップショットの `build_request_payload` も読むときに UTC で返すため、UTC 以外で保存したスナップショットで画面の一覧が読めなくなる問題も起きなくなる。保存済みのスナップショットの `build_request_payload` が UTC に直せない値を含むときは、一覧と詳細の API が 500 にならないよう、保存した期間（列の `from` / `to`）から作って返す（Issue #330）
- 日時の項目に、UTC に直すと日時の範囲を外れる値（`0001-01-01T00:00:00+01:00` など）を送ったとき、500 ではなく 422 を返すようにした（Issue #331）
  - 対象は `POST /api/incident-timeline/snapshots/manual` の `timestamp_utc`・`graph_context` の `marker_timestamp_utc` と `captured_range` の `from` / `to`・`view_request` の `anchor`、`POST /api/incident-timeline/view` の `anchor`、`POST /api/digests/run` の `from_time` / `to_time`、`GET /api/events`・`/api/events/rate-series`・`/api/logs`・`/api/logs/export.csv`・`/api/metrics` のクエリの `from` / `to`
  - `timestamp_utc` は今まで行を保存した後に 500 を返していたので、クライアントが送り直すと同じスナップショットが重複していた。これからは保存の前に 422 になる
  - `timestamp_utc` と `graph_context` の日時は UTC に揃えて保存して返すようにした。今まで `timestamp_utc` を +09:00 などで送ると、SQLite ではオフセットが落ちて 9 時間ずれた時刻で保存されていた。すでにずれて保存された値は直らない
  - `graph_context` は送った形のまま保存して返していたので、UTC 以外の値が 1 件あると画面の一覧が読めなくなっていた。保存済みの `graph_context` も読むときに UTC で返す。UTC に直せない値を含むときは、一覧と詳細が 500 にならないよう `graph_context` を null で返す
  - `POST /api/digests/run` で `from_time` と `to_time` の片方だけにタイムゾーンが無いと 500 を返していたのを、タイムゾーンの無い値を UTC とみなして受け付けるようにした
- 画面で、読めない `graph_context` を持つスナップショットが 1 件でもあると、スナップショットの一覧全体が読めずにエラーになっていたのを直した。その項目は `graph_context` が無いものとして扱う。詳細を開くときと保存した直後の応答も同じで、保存済みの `view_request` と同じ扱いである（Issue #332）
  - 読めない `graph_context` は、API を直接呼んで保存したときにできる。日時の末尾に Z が無い値は、上の Issue #331 の項のとおりサーバが UTC に揃えて返すようになった。一方、`vcenter_id` に RFC 4122 の形に合わない UUID（`11111111-1111-1111-1111-111111111111` など）を入れると、サーバは受け付けるが画面は読めない
  - `graph_context` が無い項目からグラフを開くと、期間はスナップショットに保存した期間（`build_request_payload` の `from` / `to`）に、vCenter は `build_request_payload` の `vcenter_id` に、縦線の時刻は `timestamp_utc` に戻る。指標は先頭のものになり、イベント件数の重ね表示は無くなる

## 0.2.0 - 2026-10-10

最初のリリース。今までの main（0.1.0 を名乗っていた）から更新する場合は、下の「更新の前に」を必ず読むこと。詳しい手順は [バックエンド運用ガイドの 4.2](docs/operations/backend-operations.md#42-認証を導入したバージョンへの更新) にある。

### 更新の前に（互換性のない変更）

- **認証が既定で有効になった**（`VEA_AUTH_ENABLED=true`）。更新の前に初期 admin を用意する（`VEA_BOOTSTRAP_ADMIN_USERNAME`・`VEA_BOOTSTRAP_ADMIN_PASSWORD` か、`vcenter-event-assistant-admin create-user <ユーザー名> --role admin`）。本番（`APP_ENV=production`）では admin がいないと起動しない
  - `create-user` の既定のロールは viewer なので、`--role admin` を必ず付ける。ユーザーが 1 人でもいると bootstrap の環境変数は使われないので、付け忘れたら `vcenter-event-assistant-admin set-role <ユーザー名> admin` で admin に変える
  - HTTPS で配信していて `APP_ENV=production` でなければ、`VEA_SESSION_COOKIE_SECURE=true` を設定する
  - `curl` などで API を直接呼んでいるスクリプトは、ログインしてセッション Cookie を使う必要がある。POST / PUT / PATCH / DELETE には `X-Requested-With: XMLHttpRequest` ヘッダが要る
  - リバースプロキシで行っていた認証は、二重になるので外してよい。ログインできたら `VEA_BOOTSTRAP_ADMIN_PASSWORD` を `.env` から消す
- **アラートメールの STARTTLS で、SMTP サーバの証明書を検証するようになった。自己署名や社内 CA の証明書の SMTP では、更新すると通知が止まる。** 社内 CA なら `SMTP_CA_BUNDLE` に CA のファイルを、どうしても検証できなければ `SMTP_TLS_VERIFY=false` を設定する（起動時に WARNING が出る）
  - `SMTP_CA_BUNDLE` に指定したファイルがないと起動しない。Docker では、CA のファイルをコンテナに読み取り専用でマウントし（compose なら `volumes:` に `./certs/smtp-ca.pem:/etc/vea/smtp-ca.pem:ro`）、`SMTP_CA_BUNDLE` にはコンテナの中のパス（`/etc/vea/smtp-ca.pem`）を指定する。ファイルはコンテナの実行ユーザー（UID 1000）が読める権限にする
- **プラグインのワーカーには、許可した環境変数しか渡さなくなった。** プラグインが独自の環境変数（機密値など）を読む場合は、その名前を `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH` に書く。インデックスからのインストールでは `UV_INDEX_URL` などが効かなくなったので、`VEA_PLUGIN_INDEX_URL` で指定する。本番では `uv run` を使わず `exec .venv/bin/vcenter-event-assistant` で起動する
- **Docker イメージで、アプリのコードと `.venv`（`/app`）を root の所有にした。** compose のテンプレートと、`docker run` で `/app/data` にボリュームをマウントしている場合は、そのまま動く。`/app` の下に他のファイルを書き込む構成なら、`/data` に移す
- **SSH の接続先（リモートログの収集）は、接続の直前に名前解決し、ループバック・リンクローカル（メタデータ）・マルチキャスト・予約済み・未指定のアドレスに解決される名前には接続しなくなった**（RFC1918 は今までどおり）。SSH のホスト鍵の取得・セットアップのアクション・ESXi の一覧・vCenter の接続テストに rate limit（`RATE_LIMIT_PROBE_PER_MINUTE`、既定 20 回/分）がかかる。同梱のリモートログのプラグイン 0.3.0 は plugin-api 1.5 以降が必要

### セキュリティ

2026-10 のセキュリティ監査（`docs/reports/security-audit-report-2026-10-05.md`）の指摘に対応した。

- SMTP の STARTTLS で証明書を検証する（Issue #236、PR #271）
- CSV の書き出しで、`=` `+` `-` `@` などで始まる値を数式として解釈させない（Issue #238、PR #272）
- プラグインのアップロードの一時ディレクトリを、インストールの後と起動時に消す（Issue #239、PR #272）
- プラグインの権限分離（Issue #235）
  - ワーカーとインストーラに渡す環境変数を許可リストにし、`VEA_SECRET_KEY`・`DATABASE_URL`・LLM や SMTP の資格情報を渡さない。資格情報付きのインデックスやプロキシでは wheel だけを入れる。Linux では本体のプロセスを dumpable でなくし（`VEA_PROCESS_NON_DUMPABLE`）、同じユーザーの親プロセスが秘密を持ったまま残っていれば起動時に警告する（PR #273）
  - Docker イメージで `/app` を root の所有にし、プラグインが本体のコードを書き換えられないようにした。何を守り、何を守れないかを [コレクタプラグインの「脅威モデル」](docs/operations/collector-plugins.md#脅威モデル) にまとめた（PR #275）
- SSH の接続先を、名前解決して検証した IP に接続する（DNS rebinding の対策）。許可するポートを `VEA_SSH_ALLOWED_PORTS` で絞れる。外へ接続して確かめる API に rate limit をかけた（Issue #237、PR #276）

### 主な追加

- **ログインとロール**: ローカルのユーザーでのログイン、viewer・operator・admin の 3 つのロール、ユーザー管理の画面と CLI（`vcenter-event-assistant-admin`）、パスワードの変更、ログインの rate limit とロックアウト、監査ログ（ロガー `vcenter_event_assistant.audit`）。[ログインとロール](docs/userguide/authentication.md)
- **AD / LDAP でのログイン**: 認証ディレクトリの管理画面、グループとロールの対応表、保存前の接続試験と管理者ログイン不能の防止。[AD / LDAP でのログイン](docs/userguide/directory-auth.md)
- **コレクタプラグイン**: 画面からのインストール・アンインストール・設定・「変更を反映」、プラグインごとのワーカープロセス、開発キット（`vcenter-event-assistant-plugin-api`、ひな形の生成、テストハーネス）。[プラグイン（利用者向け）](docs/userguide/plugins.md)、[コレクタプラグインの開発](docs/development/collector-plugin-authoring.md)
- **リモートログの収集**: 同梱のプラグイン VEA Remote Logs（`vea.remote.logs`）で、ESXi と vCenter のログを SSH で差分収集する。SSH 鍵の生成・ホスト鍵の承認・接続テストを画面から行う。[画面からリモートログ収集を導入する](docs/userguide/remote-log-collector.md)
- **メール通知の配送の分離**: アラートの評価と SMTP の配送を分け、送信予定を保存して再起動後も再送する。通知履歴に配送状態と試行回数を表示する

機能の全体は [機能一覧](docs/features/features_list.md) を参照する。

### 画面の改善

PR #278 で、リリースの前に画面を見直した。

- イベント・ログ・通知履歴・ダイジェストのページ切り替えを共通にし、一覧の下にも置いた。通知履歴は今まで新しい 50 件しか見えなかったが、表示件数とページ切り替えで古い通知もたどれる
- チャットとタイムラインの期間を、グラフと同じ折りたためる「表示期間」にした。条件（vCenter・閾値・メトリクス）はイベント・ログと同じツールバーの形に揃えた
- ヘッダーの利用者名・ロール・パスワード変更・ログアウトを、アバターのメニューにまとめた
- スコアルール・イベント種別ガイド・アラートルールの「ファイルにエクスポート」は operator 以上だけに表示する
- 設定のアラートとチャットのサンプルの一覧を、イベント種別ガイドと同じ折りたたみの行にした。アラートは行の中で編集して保存する。編集中にインポートなどで自分が変えた項目が変わったときは、上書きせずに知らせる（サーバ側での競合の検出は Issue #279）
- イベントの「最小スコア」の欄の幅、設定の説明文の幅と文体なども揃えた

### 廃止予告

- ダイジェストのレガシーな環境変数 `DIGEST_SCHEDULER_ENABLED`・`DIGEST_CRON` は 0.3.0 で削除する。使っていると起動時に WARNING が出る

### 既知の制約

- プラグインはアプリと同じ OS のユーザーで動く。SQLite の DB ファイル、インストール中の uv の資格情報、同じユーザーで残った親プロセスの環境変数は、プラグインから読める（Issue #274。[脅威モデル](docs/operations/collector-plugins.md#脅威モデル)）
- Samba の AD では `DOMAIN\user` の形でログインできない（Issue #266）
- グループの DN に独自 OID の属性が含まれると、対応表に登録できない（Issue #251）

### 同梱のパッケージ

- `vcenter-event-assistant-plugin-api` 1.5.0（`network.resolve_ssh_address` を追加）
- `vea-remote-log-collector` 0.3.0（接続の直前に名前解決して検証した IP に接続する）

どちらも本体と一緒に `uv sync` と Docker のビルドで入る。PyPI への公開は別に行う。
