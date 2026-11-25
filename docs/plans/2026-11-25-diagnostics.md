# 対応手順と読み取り専用の診断コマンド

最終更新: 2026-11-26（PR B マージ済み、組み込みのコマンドを実機で確認）

[障害調査を楽にする機能 10 案](2026-11-22-troubleshooting-ideas.md)（以下「10 案」）の「案 9」にあたる。案 5 の障害パターンごとに対応手順を見せ、手順の中の診断コマンドを、インシデントの詳細から ESXi と vCenter に SSH で実行して、結果をインシデントに残す。Issue は起票していない。

コードの場所は、バックエンドを `src/vcenter_event_assistant/` から、画面を `frontend/src/` から書く。行番号は、本書を書いた時点の origin/main（1fce087）のものである。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| A | 本書 | マージ済み（[PR #386](https://github.com/t-m0riyama/vcenter-event-assistant/pull/386)） |
| B | SSH の鍵と接続先の用途の分離、診断の設定（実行の対象・追加のコマンド）の表と API | マージ済み（[PR #387](https://github.com/t-m0riyama/vcenter-event-assistant/pull/387)） |
| C | 診断コマンドの実行（組み込みの一覧、ワーカーでの実行、結果の保存、監査記録） | 実装中 |
| D | 対応手順（障害パターンへの同梱と、インシデントへの候補の提示） | 未着手 |
| E | 画面: 診断の設定 | 未着手 |
| F | 画面: インシデントの手順・実行・結果と、文書 | 未着手 |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

障害の調査では、イベントやログを見たあとに、ホストに入って状態を確かめることが多い。たとえば APD（ストレージへの全パスの喪失）なら、パスとデバイスの状態を `esxcli` で見る。今は、利用者が手順を思い出し、別の端末から SSH で入って、結果をどこかに貼る必要がある。案 5 の障害パターンの説明も「まず〜を確認してください」の 1 文で終わっている。

10 案の文書で、次のことが決まっている（2 章の表の #9、5 章）。
- 手順の表示は本体で行う。コマンドの実行は本体から SSH せず、ワーカーに任せる。分離モードの設計（リモートに認証して接続するのはワーカーだけ）を回り込まないためである。
- admin だけが使える。許可したコマンドだけを動かし、監査記録を残し、ログ収集とは別の認証情報を使う。
- 本体の許可リストは安全上の境界にならないこと、ESXi の診断コマンドは強い権限を要するものが多いことを、設計の前提に書く（本書の 2 章）。
- 本番環境で強い権限のコマンドを動かすので、使うかどうかは運用側の判断に任せ、既定では無効にする。
- 案 7（インシデント記録）を前提にする。手順を実施した結果をインシデントに残すためである。

決めたこと（利用者の決定、2026-11-25）:
- **コマンドの一覧:** 組み込みの一覧に加えて、admin がコマンドを追加できる。
- **対応手順:** 案 5 の組み込みの障害パターンごとに、手順を本体に同梱する。運用者が書く手順は、今ある種別のガイドの「対処」をそのまま使う。
- **実行の場所:** インシデントの詳細からだけ実行する。結果はそのインシデントに残す。
- **対象:** ESXi と vCenter の両方。
- **追加のコマンドの引数:** admin が追加するコマンドにも引数を付けられる（計画の PR のレビューで決定）。引数の種類は組み込みのコマンドと同じ一覧から選び、何でも入る文字列の引数は作らない。値は組み込みと同じく照合して引用符で囲む。どの種類も、値に引用の要る文字が入らないように決めるので、差し込み口を雛形のどこに置いても、値が引用やコマンドの区切りを越えない（4 章）。

本書で決めたことは次のとおり。利用者にはまだ確かめていないので、計画の PR で確認してもらう。
- **組み込みのコマンドは個別に止めない:** 機能を有効にすると、組み込みの一覧はすべて使える。どれも状態を読むだけのコマンドだからである（4 章）。
- **結果は viewer も読める:** インシデントの中身と同じく、ログインした利用者は全員が結果を読める（10 章）。
- **SSH の鍵と接続先は用途で分ける:** 今ある鍵と接続先の表に「用途」の列を足し、ログ収集用と診断用を互いに使えないようにする（3 章）。
- **実行は要求の中で待つ:** 実行の要求は、結果が返るまで待つ。SSH の実行は 45 秒で打ち切り、結果の保存にさらに 10 秒までかける（4 章）。
- **認証を無効にした環境では使えない:** 認証を無効にすると全員が admin になるので、診断を有効にする設定と一緒には起動しない（2 章）。
- **監査のロガーの水準を固定する:** `LOG_LEVEL` を WARNING にすると、今は認証の監査も含めて監査ログが出なくなる。監査のロガーだけは INFO に固定する（7 章）。認証の監査にも効く。
- **解決済みのインシデントでも実行できる:** 解決したあとの確認にも使えるようにする。保持期間は延びない（10 章）。

## 1. 前提（コードで確かめたこと）

- **SSH の鍵と接続先:** 表 `ssh_credentials`（`db/models.py:748`。秘密鍵は `EncryptedString` で暗号化）と `ssh_connections`（同 756 行。ホスト・ポート・ユーザー名・鍵・取得したホスト鍵 `candidate_key`・承認したホスト鍵 `approved_key`・`revision`。鍵への外部キーは 763 行）。どちらにも用途の区別は無い。
  - API は `api/routes/plugin_setup.py` の `/api/plugins/ssh/...`。鍵の一覧（393 行）・生成とアップロード（404 行）・公開鍵（436 行）・削除（447 行）、接続先の一覧（465 行）・作成（510 行）・更新（563 行）・ホスト鍵の取得（586 行）・承認（622 行）。鍵の生成と登録は `VEA_SECRET_KEY` が無いと断る（同 412 行）。
  - このルーターは、プラグイン管理（`VEA_PLUGIN_MANAGEMENT_ENABLED`）が無効だと 404 を返す（同 78-85 行。`main.py:331-340` で、ログイン確認より先に評価するようにマウントする）。admin だけが呼べる。
  - ホスト鍵の取得は本体が認証なしで接続して行い（同 586-620 行）、名前解決して検証した IP に接続する（`resolve_ssh_address`）。
  - 収集中の接続先は変更できない（同 535 行の `ensure_not_active`）。接続先を削除する API は無い。鍵は、接続先から使われていると削除できない（同 447 行）。
  - 収集の設定が参照する接続先は、設定のスキーマの `x-vea-ssh-connection` から探す（`services/ssh_management.py:55` の `ssh_objects`）。接続先を DB から引くのは、テストの済んだ設定との照合（同 87 行の `reference_digest`）と、実行時の鍵の受け渡し（同 121 行の `materialize_ssh`）の 2 つだけである。この 2 つを、設定の検証とテストと適用（`plugin_setup.py:246・273・320`）、有効への切り替え（`api/routes/plugins.py:228`）、setup の実行（`services/plugin_configuration.py:148`）、定期の収集（`plugins/runtime.py:388`）が呼ぶ。`validate_targets`（`services/plugin_configuration.py:104`）は vCenter の ID しか見ない。
  - `materialize_ssh` は、分離しないモードでは鍵をディスクの一時ファイルに書いてパスを渡し、分離モードでは中身を要求に入れる（`plugins/remote.py:357`）。
  - SSH のポートは `VEA_SSH_ALLOWED_PORTS` で絞れる（`services/ssh_management.py:21` の `check_ssh_port`、`settings.py:268`）。
- **ワーカー:** `plugins/remote.py:99` の `CollectorWorker` が、ワーカーとの 1 本の JSON Lines の通信路を持つ。
  - 分離モード（`VEA_PLUGIN_SERVICE_SOCKET_DIR` あり）では、ワーカーのサービスにソケットで接続して、別 UID のセッションを作る（同 121-142 行。作るまでに最大 6 秒、同 131 行）。プラグインのパスが空のセッションも作れる（`plugins/service.py:107-113`）。そうでなければ、アプリと同じ UID の子プロセスを起動する（`remote.py:143-153`）。
  - 要求は 8 MiB まで、応答も 8 MiB まで（`plugins/wire.py:32-33`）。要求には時間の上限を付け、超えるとワーカーを kill する（`remote.py:155` の `request`）。止めるときは最大 5 秒待つ（同 252・263 行）。
  - ワーカーの側は `plugins/worker.py:184` の `_handle` が `op` で分ける。`ping` と `discover` はプラグインを読み込まずに処理し、それ以外は `request["entry_point"]` でプラグインを読み込む（同 194-200 行）。`collect` と `setup` は、要求に入れたファイル（鍵と known_hosts）を、要求のあいだだけ一時ファイルにする（同 208-226 行、`plugins/request_files.py:37`）。一時ファイルの権限は 0400 で（同 31 行）、同じ UID のプロセスなら読める。
  - 失敗のとき、ワーカーは例外の型名だけを返す（`worker.py:301`）。
  - ワーカーに渡す環境変数は限られていて、モックモードや `VEA_SSH_ALLOWED_PORTS` は渡らない（`plugins/subprocess_env.py:103-117`）。
  - 分離モードでも、ワーカーどうしは同じ UID で動く（`docs/operations/collector-plugins.md:185-189`）。
  - asyncssh は、本体が依存する `vea-remote-log-collector` の依存として入っている（`packages/remote-log-collector/pyproject.toml:8`）。本体の依存には直接書いていない。asyncssh 2.24.1 は、秘密鍵（`import_private_key`）と known_hosts（`import_known_hosts` が返す `SSHKnownHosts`）をメモリのまま接続に渡せる。
- **SSH でのコマンドの実行:** リモートログのプラグイン（`packages/remote-log-collector/src/vea_remote_log_collector/transport.py`）が手本になる。
  - 接続は、検証した IP に、ホスト鍵の別名を名前にして開く。パスワード認証・キーボード対話認証・エージェント・SSH の設定ファイルを使わない（同 257 行の `open_reader`）。
  - 出力は標準出力・標準エラーともバイト数の上限で読み、超えたら失敗にする（同 61-75 行・86-124 行）。受信のウィンドウは 64 KiB（同 22 行）。
  - vCenter は、ログインのシェルが appliance shell か Bash かを、固定のコマンドで確かめてから `shell /bin/bash -c` か `/bin/bash -c` を前に付ける（同 126-145 行）。さらに `export PATH=/usr/sbin:/usr/bin:/sbin:/bin; ` を前に付けてから、全体を `shlex.quote` で囲む（同 147-152 行）。この処理はプラグインのパッケージの中にあり、本体からは使っていない。
- **障害パターン:** 組み込みの 7 種類（`services/event_patterns/definitions.py:44` の `BUILTIN_PATTERNS`）。ID は `host-conn-flapping`・`host-reconnect-failed`・`apd-timeout`・`apd-repeated`・`nic-link-flapping`・`ha-failover`・`vmotion-failures`。`description` は「まず〜を確認してください」で終わる 2 文である。
  - 対象は、`ha-failover` だけがクラスタ（同 110 行）で、ほかはホストである。
  - 障害パターンのアラートの `context_key` は `{vcenter_id}:{entity_moid}:{pattern_id}`（`services/alerting/alert_eval_common.py:39`）。最初と最後の区切りで分ける関数がある（同 44 行）。
- **インシデント:** 表 `incidents`・`incident_entries`（経過）・`incident_events`（イベントの写し）・`incident_alerts`（通知の写し）など（`db/models.py:627-738`）。
  - 経過の種類は `note`・`change`・`link`（`api/schemas/incidents.py:15` の `EntryKind`、画面は `frontend/src/api/schemas/incidents.ts:71` の `z.enum`）。メモは 1 件 4,000 文字まで（`api/schemas/incidents.py:100`）、1 件のインシデントに 1,000 件まで（`services/incidents.py:33` の `MAX_NOTES`。数えるのは `note` だけ、`api/routes/incidents.py:197-214`）。
  - 書き込みは、要求のセッションとは別のセッション（`api/routes/incidents.py:63-65` の `_incident_write_session`）で、先に `lock_incident`（`services/incidents.py:192`）でインシデントの行をロックしてから行う。
  - 通知の写しは、ルールの種別（`rule_type`）・`context_key`・vCenter の ID・対象の moid を持つ（`db/models.py:695`）。イベントの写しは、種別と主な対象の種別・moid だけを持つ（`services/incidents.py:271`）。主な対象は VM がホストより先に選ばれる（`packages/plugin-api/src/vcenter_event_assistant_plugin_api/vmware.py:172-178`）ので、VM のイベントでは VM の moid になる。
  - 解決から `INCIDENT_RETENTION_DAYS`（既定 90 日、`settings.py:99`）で消える（`services/ingestion.py:315`）。経過・写しは CASCADE で一緒に消える。
  - インシデントの中身は、チャット（LLM）にも案 10 の出力にも入らない（[案 7 の計画書](2026-11-25-incident-records.md) の 3 章「チャットには渡さない」）。
- **要求のセッション:** ログインの確認（`api/auth_deps.py:89-95`）は要求の単位のセッション（`api/deps.py:20-37`）を使い、最終利用時刻を更新したときだけ commit する（`auth_deps.py:112-115`）。それ以外では、要求が終わるまでトランザクションが開いたままになる。
- **認証を無効にしたとき:** 全員が admin の `anonymous` になる（`api/auth_deps.py:68`）。CSRF の対策も、認証が有効なときしか付かない（`main.py:299-301`）。認証を無効にできるのは本番以外だけである（`settings.py:823-829`）。
- **レート制限:** 外へ接続して確かめる API は、`probe` の枠で数える（`main.py:108-122`）。
- **監査ログ:** `auth/audit.py` の `audit()` が、ロガー `vcenter_event_assistant.audit` に `AUDIT event=... key=value ...` の 1 行を出す。値に空白や制御文字があれば `repr` で 1 行に収める。既定の水準は INFO で、ロガーの水準は親の `vcenter_event_assistant` から `LOG_LEVEL` を受け継ぐ（`logging_config.py:47-51`）。今は認証と利用者の管理だけが使っている。
- **ESXi の一覧:** `GET /api/plugins/vcenters/{id}/hosts`（`api/routes/plugin_setup.py:642`）が、vCenter に接続して ESXi の moid と名前を返す。プラグイン管理の 404 の仕組みの下にある。モックモードでは `id: "mock-esxi"` の 1 台を返す（同 658-661 行）。
- **設定の API:** `GET /api/config`（`api/routes/config.py:21`、応答は `AppConfigResponse`）が、モックモードなどの画面向けの値を返す。
- **PostgreSQL の CI:** `.github/workflows/ci.yml:210-229` は、決まったファイルを `-k "postgres and (...)"` で絞って流す。新しいテストは、ファイルを一覧に足し、`-k` にも語を足さないと流れない。
- **SQLite の移行:** 移行は `PRAGMA foreign_keys=ON` の接続で流れる。表を作り直すと、参照されている表の `DROP TABLE` が外部キーの違反で失敗するので、今の移行は作り直しを避けている（`alembic/versions/e8f9a0b1c2d3_store_event_entities.py:4-6`、`d1e2f3a4b5c6_add_alert_history_occurred_at.py:10-13`）。
- **移行:** 今の head は `c2d3e4f5a6b7`（`alembic/versions/c2d3e4f5a6b7_add_incident_records.py`）。実装のときに確かめ直す。

ESXi の権限については、公式の文書で次のことを確かめた。
- ESXi Shell（SSH を含む）を使えるのは、root と Administrator ロールのユーザーである（[Using the ESXi Shell](https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/8-0/vsphere-security/securing-esxi-hosts/using-the-esxi-shell.html)）。読み取り専用のロールは書かれていない。
- ESXi 7・8・9 のローカルユーザーは、Administrator ロールでも、ユーザーの設定で「Shell Access」を明示的に有効にしないと SSH でログインできない（[Broadcom KB 426814](https://knowledge.broadcom.com/external/article/426814/unable-to-access-ssh-on-some-esxi-hosts.html)）。

## 2. 安全の考え方

この機能は、admin の操作で、強い権限を持つアカウントとしてホストにコマンドを送る。何が安全を支え、何が支えないかを、文書と画面にそのまま書く。

**安全を支えるもの**
- **対象側のアカウントと鍵:** 診断用のアカウントと鍵を、ログ収集とは別に用意する。ログ収集の鍵が漏れても、診断のアカウントには入れない。逆も同じである。
- **既定で無効:** `VEA_DIAGNOSTICS_ENABLED=true` を環境変数で設定しない限り、診断の設定と実行の API は存在を伏せて 404 を返す。画面からは有効にできない。
- **認証が必須:** `VEA_DIAGNOSTICS_ENABLED=true` と `VEA_AUTH_ENABLED=false` の組み合わせは、設定の検証で起動時に断る。認証が無効だと全員が admin になり、CSRF の対策も付かないためである。
- **admin だけ:** 設定と実行は admin だけができる。
- **鍵をファイルにしない:** 診断の鍵と known_hosts は、ワーカーの中でもファイルに書かず、メモリのまま asyncssh に渡す（4 章）。ワーカーは同じ UID で動くので、ファイルにするとほかのプラグインのワーカーから読めるためである。診断のワーカーは、鍵を含む要求を読む前に自分を `prctl(PR_SET_DUMPABLE, 0)` にして（`process_hardening.py:53` の `harden_process` と同じ処理。Linux のときだけ効く）、同じ UID のプロセスからメモリを読まれにくくする。そのため本体は、鍵を含まない `op="harden"` を先に送り、応答が返ってから `diagnose` を送る（4 章）。分離モードで要求を中継するワーカーのサービスのプロセスも、`worker` の役割のときだけ、起動時に同じ処理をする（`service.py` の `_serve`）。サービスは今のログ収集も担うので、失敗しても止めずに警告を出す。子のワーカーは起動（execve）で元に戻るので、ワーカーの側は `harden` で確かめる。
- **監査記録:** 実行の前と後、拒否したとき、設定を変えたときに、監査ログに 1 行ずつ残す（7 章）。インシデントの記録は監査記録として扱わない。admin が消せ、解決から 90 日で消えるためである。

**安全を支えないもの**
- **本体の許可リスト:** 本体は、暗号を解いた秘密鍵を持っている。本体が乗っ取られれば、許可リストを通らずに鍵を使える。分離モードでも、鍵をワーカーに渡すのは本体である。分離モードでないときは、ワーカーは本体と同じ UID で動く。ワーカーの側でもコマンドと引数を確かめ直すが（4 章）、多重の確認であって境界ではない。
- **ワーカーの分離:** 分離モードでも、ワーカーどうしと、要求を中継するワーカーのサービス（`plugins/service.py:85-91` の `_read_worker_requests`）は同じ UID で動く。`PR_SET_DUMPABLE` は `/proc` からの読み取りを防ぐが、同じ UID で動く悪意のあるプラグインを無害にはできない。鍵は、要求の通信路（ソケットかパイプ）を通る。ログ収集の鍵も、今から同じ経路を通っている。
- **「読み取り専用」という分類:** 組み込みのコマンドは状態を読むだけのものを選ぶが、それを実行するアカウントは Administrator ロールを持つ。admin が追加するコマンドは、何をするかを本体では確かめられない。
- **インシデントの記録:** 改ざん耐性が無いので証跡にならない（10 案の 5 章の #7）。

**運用側の対策として文書に書くもの**
- 診断用のアカウントは、必要なホストにだけ作り、使わないときは Shell Access を外す。
- 本体（分離モードならワーカー）から対象への SSH を、ネットワークで必要な宛先だけに絞る。
- 信頼できるプラグインだけを入れる（今の文書の「脅威モデル」と同じ）。診断を有効にすると、プラグインのワーカーが診断の鍵に近づく機会が増える。
- `authorized_keys` の接続元の制限（`from=`）などが ESXi 8 で使えるかは、実機で確かめてから文書に書く。確かめるまでは書かない。

## 3. データの形

### SSH の鍵と接続先の用途

`ssh_credentials` と `ssh_connections` に `purpose` の列を足す。値は `logs` と `diagnostics` の 2 つにする。

- **移行:** 表を作り直さず、`op.add_column` に `server_default='logs'` と名前付きの CHECK（`purpose IN ('logs', 'diagnostics')`、名前はモデルと同じ）を付けた列を渡して足す。今ある行は `logs` になる。alembic 1.18.4 と SQLAlchemy 2.0.48 では、SQLite でも `ADD COLUMN ... CONSTRAINT ck_... CHECK (...)` が出力され、違反する値の挿入は失敗することを確かめた。本番の DB は新しく作るときも alembic で作る（`db/alembic_runner.py:147-148`）ので、テストの `create_all` と同じ制約になる。PostgreSQL の移行のテストで、`pg_constraint` に制約があることを確かめる。
- 接続先の用途は、使う鍵の用途と同じでなければならない。作成と更新で確かめる。
- 用途は作ったあとで変えられない。
- 用途を確かめて接続先を引く関数を 1 つ作り（`services/ssh_management.py`）、`reference_digest` と `materialize_ssh` の両方から使う。収集の設定が参照する接続先は `logs` でなければならない。
- 今の `/api/plugins/ssh/...` は、鍵も接続先も `logs` の行だけを扱う。
  - 一覧は `logs` の行だけを返す。作る行は `logs` にする。
  - `diagnostics` の行は、鍵の公開鍵と削除、接続先の更新・ホスト鍵の取得・承認のすべてで 404 にする。
  - 接続先の作成と更新で選べる鍵も `logs` だけにする（同 516・572 行の確認）。
- 診断の API（`/api/diagnostics/ssh/...`）は、同じ処理を `diagnostics` の用途に固定して呼ぶ。処理は `plugin_setup.py` から切り出して、用途を引数にする。

### 実行の対象（`diagnostic_targets`）

インシデントに出てくるホスト（moid）から、使う接続先を決めるための表である。

| 列 | 型 | 説明 |
|---|---|---|
| `id` | UUID | 主キー |
| `vcenter_id` | UUID | `vcenters.id` への外部キー。vCenter を消すと一緒に消える（CASCADE） |
| `product` | 文字列 | `esxi` か `vcenter` |
| `host_moid` | 文字列（NULL 可） | ESXi の moid。`vcenter` のときは NULL |
| `host_name` | 文字列 | 表示用の名前（登録したときの ESXi の名前か vCenter の名前） |
| `ssh_connection_id` | UUID | `ssh_connections.id` への外部キー（RESTRICT）。用途が `diagnostics` の接続先だけ |
| `created_by`・`updated_by`・`created_at`・`updated_at` | | 誰がいつ変えたか |
| `revision` | UUID | 楽観ロック |

- CHECK `(product = 'vcenter') = (host_moid IS NULL)` を付ける（新しい表なので SQLite でも付く）。
- ESXi は `(vcenter_id, host_moid)` の通常の一意制約にする。vCenter の行は `host_moid` が NULL なので、この制約では重なりを防げない。`vcenter_id` に `WHERE product = 'vcenter'` の部分一意索引を足す（前例は `db/models.py:108-109`）。

### 追加のコマンド（`diagnostic_commands`）

admin が追加するコマンドの表である。組み込みのコマンドはコードに持ち、この表には入れない。

| 列 | 型 | 説明 |
|---|---|---|
| `id` | UUID | 主キー |
| `product` | 文字列 | `esxi` か `vcenter` |
| `title` | 文字列（100 文字まで） | 名前 |
| `description` | 文字列（1,000 文字まで） | 説明 |
| `template` | 文字列（1,000 文字まで） | コマンドの雛形。改行・NUL・制御文字は不可。引数の差し込み口 `{{名前}}` を書ける（4 章） |
| `param_definitions` | JSON | 引数の定義 `[{"name", "type"}]`。8 個まで。引数の無いコマンドは空の配列 |
| `created_by`・`updated_by`・`created_at`・`updated_at`・`revision` | | 対象の表と同じ |

### 実行の結果（`incident_diagnostic_runs`）

| 列 | 型 | 説明 |
|---|---|---|
| `id` | 整数 | 主キー（SQLite では `AUTOINCREMENT`） |
| `incident_id` | UUID | `incidents.id` への外部キー（CASCADE）、索引 |
| `command_kind` | 文字列 | `builtin` か `custom` |
| `command_ref` | 文字列 | 組み込みならコマンドの ID、追加なら `diagnostic_commands.id` の文字列（外部キーにしない） |
| `command_title` | 文字列 | 実行した時点の名前の写し |
| `command_line` | 文字列 | 本体が組み立てた、送るコマンドの文字列の写し（4 章）。vCenter で前に付けるシェルの呼び出しと `export PATH=...` は含めない |
| `executed` | 真偽（NULL 可） | ホストでコマンドの実行を要求できたか。NULL は分からない（4 章） |
| `params` | JSON | コマンドに渡した引数（正規化した値）。組み込みと追加の両方 |
| `target_id` | UUID（NULL 可） | 外部キーにしない。対象を消しても結果は残す |
| `product`・`host_name`・`ssh_host`・`ssh_port`・`ssh_username` | | 実行した時点の写し |
| `status` | 文字列 | `succeeded`（終了コード 0）・`failed`（0 以外）・`error`（4 章の失敗の区分） |
| `exit_status` | 整数（NULL 可） | 終了コード |
| `error_code` | 文字列（NULL 可） | `error` の理由の区分。例外の文言は入れない |
| `stdout`・`stderr` | Text | 出力（4 章の上限で切ったもの） |
| `stdout_truncated`・`stderr_truncated` | 真偽 | 上限で切ったか |
| `elapsed_ms` | 整数 | 所要時間 |
| `started_at`・`finished_at` | 時刻 | |
| `run_by` | 文字列 | 実行した利用者 |

- 1 件のインシデントにつき 100 件までにする。超えると 409（`X-VEA-Error-Code: incident_diagnostic_limit`）を返す。出力の上限と合わせて、1 件のインシデントの結果は最大でおよそ 8 MiB になる。
- インシデントの詳細（`read_incident_detail`）は、結果の一覧を出力の列を除いて返す。詳細の取得（`api/routes/incidents.py:145`）のほか、作成（同 172 行）と変更（同 189 行）の応答も同じ関数を使うので、そこにも入る。出力は 1 件ずつ別の API で読む（6 章）。

### 経過

経過の種類に `diagnostic` を足す。実行のたびに「診断「NIC の一覧」を esx01.example.com で実行した（終了コード 0）」のような 1 行を自動で書く。メモの上限（`MAX_NOTES`）には数えない。結果を書くときは `mark_incident_updated` も呼び、一覧の「最終更新」に出す。

## 4. コマンドと実行

### 組み込みのコマンド

コードの中の一覧（`services/diagnostics/catalog.py`）に持つ。1 件は、ID・対象の製品・名前・説明・コマンドの雛形・引数の定義を持つ。引数の定義は、追加のコマンドと同じく名前と種類の組にする。名前は、同じ種類を 2 つ使わない限り種類と同じ名前にする（`{{vmk}}`）。

雛形の差し込み口は `{{名前}}` と書く。雛形の確認と組み立ては、追加のコマンドと同じ関数で行う（下の「追加のコマンド」）。

引数の種類は次の 4 つに限る。照合は `re.fullmatch` で行い（`re.match` と `$` では末尾の改行を通す）、正規化した値を `shlex.quote` で囲んでから雛形に入れる。

どの種類も、正規化した値が空でなく、`shlex.quote` で引用符の付かない文字（`[A-Za-z0-9@%+=:,./_-]`）だけからなり、先頭が英数字であるように決める。今の 4 種類はこの性質を持つので、`shlex.quote` は値をそのまま返す。この性質があるので、差し込み口を雛形のどこに置いても（引用符の中、`$(...)` の中、ほかの文字とつながった位置でも）、値が引用やコマンドの区切りを越えない。値だけで 1 語になる位置では、`-` や `+` で始まるオプションとしても読まれない。

ただし、`$` の直後、`${...}` の中、`$((...))` の中に置くと、値が変数の名前や計算式として読まれる。また、bash の `$'...'` の中では、雛形の側で差し込み口の手前に書いたエスケープが、値の先頭の文字を取り込む。`$'\{{device}}'` に値 `x41` を入れると `A` になり、`$'\1{{ipv4}}'` に `192.168.0.1` を入れると、先頭の `1` がエスケープに取り込まれる（どちらも bash で確かめた）。値は引用の外には出ないが、プレビューで見せた引数とは違う値が渡る。`{{` の直前が `$` か `\` の雛形は、登録で断る（下の「追加のコマンド」）。`${...}` と `$((...))` の中、`$'...'` の中で `\1`・`\c`・`\x4` のようなエスケープの直後に置いた差し込み口は確かめず、値がそのままの文字として渡ることを保証しない。雛形も値も admin が入れ、組み立てた文字列はプレビューでそのまま見せるためである（11 章）。`$'...'` を含む雛形を一律に断ることも考えたが、`grep -E '^vmk[0-9]+$'` のように、行末の `$` と閉じる引用符が並ぶふつうの書き方まで断ることになるので採らない。

差し込み口の位置をシェルの構文に照らして確かめる方法は採らない。`shlex` はシェルの構文解析ではなく、`"$(...)"` の中で引用が新しく始まることや、bash の `$'...'` を知らないので、確認を通っても値が引用の外に出る雛形を作れるためである。種類を足すときもこの性質を守り、種類ごとにテストで確かめる。空白や引用符の要る種類は、この仕組みでは足さない（11 章）。

| 種類 | 確かめ方 |
|---|---|
| `vmnic` | `vmnic[0-9]{1,3}` |
| `vmk` | `vmk[0-9]{1,3}` |
| `ipv4` | `ipaddress.IPv4Address` で読め、`str()` で正規化した値を使う。IPv6（`vmkping -6` が要る）とスコープ ID（`%`）は、最初の版では扱わない |
| `device` | `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`（`naa.` などのデバイス ID）。先頭の `-` を断り、オプションを差し込ませない |

最初の一覧は次のとおり。2026-11-26 に、利用者が実機で実行した結果で確かめた（Claude は実機に接続していない）。

- **ESXi:** ESXi 8.0.3（build-24262298）。root ではなく、Administrator ロールと Shell Access を付けたローカルユーザーで実行し、全件が権限のエラーなく動いた。診断用のアカウントはこの権限で足りる。HA が無効のホストである。
- **vCenter:** vCenter 8.0 のアプライアンス。root で、ログインシェルを事前に bash に変えた状態で実行した。そのため、ログインした直後の appliance shell を経由する経路（前置きの判定）は、実機では確かめていない。この判定は、ログ収集のプラグインの今の処理と同じ方法で行う（4 章「ワーカーの中の処理」）。
- **所要時間:** `service-control --status --all` が 2 秒、`vmkping` が約 3 秒で、ほかは 1 秒以内だった。ESXi の秒数は貼り付けた手順の崩れで正確には測れていないが、全件で数秒だった。45 秒の期限に十分収まる。
- **出力の大きさ:** どれも 3 KiB 未満で、64 KiB の上限に収まる。`esxi.paths` だけは、パスの数に比例して増える（1 本でおよそ 800 バイト）。

| ID | 製品 | コマンド | 用途 | 実機での確認 |
|---|---|---|---|---|
| `esxi.hostname` | ESXi | `esxcli system hostname get` | 接続したホストの名前（取り違えの確認） | 確認済み。`Domain Name`・`Fully Qualified Domain Name`・`Host Name` の 3 行 |
| `esxi.version` | ESXi | `esxcli system version get` | 版とビルド | 確認済み。`Product`・`Version`・`Build`・`Update`・`Patch` の 5 行 |
| `esxi.uptime` | ESXi | `esxcli system stats uptime get` | 再起動したか | 確認済み。マイクロ秒の数字 1 つだけを出す（例: `1643109302446` で約 19 日）。説明に単位を書く |
| `esxi.maintenance` | ESXi | `esxcli system maintenanceMode get` | メンテナンスモード | 確認済み。`Disabled` か `Enabled` の 1 語 |
| `esxi.hostd` | ESXi | `/etc/init.d/hostd status` | 管理エージェント（hostd） | 確認済み。`hostd is running.` |
| `esxi.vpxa` | ESXi | `/etc/init.d/vpxa status` | vCenter のエージェント（vpxa） | 確認済み。`vpxa is running` |
| `esxi.fdm` | ESXi | `/etc/init.d/vmware-fdm status` | HA のエージェント | 一部だけ確認。HA が無効のホストでは、スクリプトが無く `not found`（終了コード 127）になる。HA が有効なときの出力は、試せるホストが無く確かめていない。`ha-failover` の手順で最も知りたい情報なので、利用者の判断で一覧に入れる。説明に「HA が無効のホストでは not found になる」と書く |
| `esxi.vmk` | ESXi | `esxcli network ip interface ipv4 get` | VMkernel のアドレス | 確認済み。vmk ごとに 1 行の表（名前・アドレス・ネットマスク・ブロードキャスト・種類・ゲートウェイ・DHCP DNS） |
| `esxi.ping` | ESXi | `vmkping -c 3 -I {{vmk}} {{ipv4}}` | VMkernel からの疎通 | 確認済み。約 3 秒。応答 3 行と統計 |
| `esxi.nic` | ESXi | `esxcli network nic list` | 物理 NIC のリンク | 確認済み。NIC ごとに 1 行の表（リンクの状態・速度・MTU など） |
| `esxi.nic-stats` | ESXi | `esxcli network nic stats get -n {{vmnic}}` | 物理 NIC の統計 | 確認済み。送受信のパケット数・バイト数と、エラーの種類ごとの数（約 700 バイト） |
| `esxi.paths` | ESXi | `esxcli storage core path list` | ストレージのパス | 確認済み。パスごとに 18 行ほど（1 本でおよそ 800 バイト）。パスが 80 本を超える環境では 64 KiB で切れるので、説明にそう書く |
| `esxi.device` | ESXi | `esxcli storage core device list -d {{device}}` | ストレージのデバイス | 一部だけ確認。コマンドがあることと、無いデバイスを指定したときの出力（`Unable to find device with name ...`、終了コード 1）は確かめた。成功したときの出力は確かめていないので、PR F の撮影の前に確かめる。デバイス名は `t10.NVMe____…` の形もあり、`device` の種類に合う |
| `esxi.adapters` | ESXi | `esxcli storage core adapter list` | ストレージのアダプタ | 確認済み。HBA ごとに 1 行の表 |
| `vcenter.hostname` | vCenter | `hostname -f` | 接続したホストの名前 | 確認済み。FQDN の 1 行 |
| `vcenter.services` | vCenter | `service-control --status --all` | vCenter のサービス | 確認済み。2 秒。先頭に空行が 1 行あり、`Running:` と `Stopped:` の下にサービス名が空白区切りで並ぶ。vCenter HA を構成していなければ `vmware-vcha` が `Stopped:` に出るのはふつうだと説明に書く |
| `vcenter.disk` | vCenter | `df -h` | ディスクの空き | 確認済み。約 2 KiB。ファイルシステムとコンテナの数だけ行が増える |
| `vcenter.memory` | vCenter | `free -m` | メモリ | 確認済み |
| `vcenter.uptime` | vCenter | `uptime` | 稼働時間と負荷 | 確認済み |

`vmkping` は状態を読むコマンドではないが、ICMP を 3 回送るだけで設定は変えない。疎通の確認は障害パターンの手順の中心なので入れる。

ESXi のコマンドを vCenter に送ると、`esxcli` などが無いので終了コード 127 になることも、実機で確かめた。手順 2 で、コマンドの製品と対象の製品の一致を確かめる理由である。

### 追加のコマンド

- admin は、製品ごとにコマンドの雛形を登録する。雛形には引数の差し込み口 `{{名前}}` を書ける。差し込み口の無い雛形は、固定の文字列としてそのまま送る。ESXi ではログインのシェル（ESXi の sh）が解釈し、vCenter では組み込みと同じ前置きを付ける。
- 引数は 8 個まで定義できる。1 個の引数は名前と種類を持つ。名前は `[a-z][a-z0-9_]{0,31}` に合うものにし、1 つのコマンドの中で重ねない。種類は組み込みのコマンドと同じ一覧（上の表）から選ぶ。
- 何でも入る文字列の種類は作らない。作ると、値の安全をコマンドごとの意味（`-f` や `../` を通してよいか）に頼ることになり、本体の一律の照合では守れないためである。種類が足りなければ、上の性質を守ってコードの一覧に足す。
- 引数はすべて必須で、既定値は持たない。
- 登録（作成と更新）のときに雛形を確かめ、合わなければ 422（`X-VEA-Error-Code: diagnostic_template_invalid`）で断る。本文には、理由の区分と、関わる引数の名前を返す。確かめることと理由の区分は次のとおり。
  - 改行・NUL・制御文字を含まないこと（`control_character`）。
  - `{{` と `}}` で英数字と `_` だけの文字列を囲んだ部分（`\{\{[A-Za-z0-9_]+\}\}`）が、どれも定義した引数の名前と一致すること（`undefined_parameter`）。`{{Vmk}}` のような打ち間違いを、そのままの文字として送らずに断るためである。そのため、`{{名前}}` の形の文字列をそのままの文字として送ることはできない。この形に当たらない `{{` は、そのままの文字として送る。
  - 定義した引数が、雛形に 1 回以上現れること（`unused_parameter`）。
  - 差し込み口の直前が `$` でないこと（`dollar_prefix`）。`${{device}}` は、値 `HOME` で `$HOME` に展開されるためである。
  - 差し込み口の直前が `\` でないこと（`backslash_prefix`）。`$'\{{device}}'` は、値 `x41` で `A` になるためである。
  - 引数の名前の形（`invalid_parameter_name`）、名前の重なり（`duplicate_parameter`）、種類が一覧にあること（`unknown_parameter_type`）、8 個以下であること（`too_many_parameters`）。
- 差し込み口の位置は確かめない。`--nic-name={{vmnic}}` や `/net/pNics/{{vmnic}}/stats` のように、オプションやパスの中にも置ける。安全は、上の種類の性質で守る。差し込み口をコマンドの名前の位置に置くこと（雛形が `{{device}}` だけ、など）も防がない。雛形も値も admin が入れるので、admin は同じことを固定の文字列でも書けるためである。
- 実行のときは、組み込みのコマンドと同じく、値を `re.fullmatch` で照合し、正規化した値を `shlex.quote` で囲んでから差し込む。雛形の確認と組み立ては、組み込みと同じ関数（`services/diagnostics/catalog.py`）で行う。実行のときも、保存した雛形をこの関数で確かめ直す。
- 本体は、雛形が何をするコマンドかを確かめない。画面と文書に「読み取り専用かどうかは本体では確かめない」と書く。
- 作成・更新・削除は監査ログに残し、雛形と引数の定義もそのまま記録する。
- 削除や変更をしても、実行の結果には、名前・組み立てた文字列・引数の値の写しが残る。

### 実行の流れ

`POST /api/diagnostics/incidents/{id}/runs` で実行する。要求の本文は次の形にする。

```json
{"target_id": "UUID", "command": {"builtin": "esxi.ping"} | {"custom": "UUID"}, "params": {"名前": "値"}, "fingerprint": "16 進の文字列"}
```

- `fingerprint` は、実行の前に見せた内容の指紋である。`POST /api/diagnostics/incidents/{id}/runs/preview` が、同じ本文（`fingerprint` を除く）から、手順 2 と同じ確認をして、送る文字列（`command_line`）・対象のホスト名・接続先（ホスト・ポート・ユーザー名）と指紋を返す。指紋は、コマンドの区分と ID、`command_line`、製品、対象の ID とホスト名、接続先のホスト・ポート・ユーザー名、承認したホスト鍵を、キーを並べた JSON にして SHA-256 を取った値にする。画面は、この応答の文字列と接続先をそのまま見せ、実行の要求に指紋を入れる。画面で文字列を組み立てると、本体の組み立てとずれるためである。
- プレビューは SSH をしない。確かめに失敗したら実行と同じ 4xx を返すが、実行していないので監査ログは書かない。レート制限は付けない。

1. 機能が有効であること、admin であることを確かめる（ゲートと `RequireAdmin`）。ログインの確認に使った要求のセッションを commit して、DB の接続を返す。SSH のあいだに、PostgreSQL で接続をつかんだままにせず、SQLite で書き込みを待たせないためである。
2. `session_scope(settings=..., isolate_memory=True)` で開いた読み取りのセッションで、次を確かめて値を取り出し、セッションを閉じる。ここで取り出した値だけを手順 5 で送り、読み直さない。
   - インシデントがあること。結果が 100 件未満であること。
   - 対象・接続先・鍵・コマンド。接続先と鍵の用途が `diagnostics` で、ホスト鍵が承認済みであること。ポートが `VEA_SSH_ALLOWED_PORTS` に入っていること。コマンドの製品が対象の製品と同じであること。引数が定義に合うこと（組み込みは一覧の定義、追加はその行の定義）。追加のコマンドは、保存した雛形も確かめ直す。
   - 対象・コマンドが無ければ 404 を返す。引数の誤りは 422（`X-VEA-Error-Code: diagnostic_params_invalid`）で、本文に誤った引数の名前と理由（`missing`・`unknown`・`invalid_value`）の一覧を返す。画面は、これで誤った欄を示す。保存した雛形が確かめ直しを通らないときは 422（`diagnostic_template_invalid`）を返す。
   - 確かめたあとで組み立てた内容から指紋を計算し、要求の `fingerprint` と比べる。違えば 409（`X-VEA-Error-Code: diagnostic_changed`）を返す。プレビューのあとでコマンド・対象・接続先のどれかが変わったとき、画面で見せた内容と違うものを送らないためである。
   - 確かめに失敗したら、監査ログに `rejected` を書いて 4xx を返す。
3. 空きを確かめる。数える単位は接続先（`ssh_connection_id`）ごとに 1 本、全体で 2 本までにする。空きが無ければ待たずに 409（`X-VEA-Error-Code: diagnostic_busy`）を返し、監査ログに `rejected` を書く。数えるのはプロセスの中だけで、本体を複数起動する構成は今も想定していない。
4. 空きを取ったら、`await` を挟まずに、要求から切り離したタスクを作る（下の「切り離したタスク」）。手順 5〜7 はこのタスクの中で動く。
5. 監査ログに `started` を書く（本体が組み立てた文字列を入れる）。45 秒の期限の中で、プラグインのパスを持たない `CollectorWorker([], label="diagnostics")` を起動し、鍵を含まない `op="harden"` を送って応答を待ってから、`op="diagnose"` を送る。ワーカーを止めるところまでを、この期限で包む。時間は次のように割り振る。ワーカーの中の打ち切り（要求の `deadline_seconds`）は期限の残りから 7 秒を引いた値、本体の `request(timeout=...)` は残りから 5 秒を引いた値にし、最後の 5 秒をワーカーの停止に使う。ワーカーの中の打ち切りを先に来させて、途中までの出力を本体に返させるためである。本体の期限が先に切れるとワーカーは kill され（`plugins/remote.py:181-190・199-201`）、途中までの出力は失われる。
6. 期限の外で、別の短い上限（10 秒）を付けて、新しいセッションで `lock_incident` してから、結果の件数を数え直す。100 件に達していれば、結果を捨てて 409 を返す。インシデントが消えていれば 404 を返す。どちらも監査ログに `discarded` を書く。そうでなければ、結果と経過の行を書き、`mark_incident_updated` を呼ぶ。
   - 保存が 10 秒の上限を超えたとき、または DB の書き込みか commit が例外で失敗したときは、巻き戻してから、監査ログに `discarded` を書いて 503（`X-VEA-Error-Code: diagnostic_save_failed`）を返す。理由は `save_timeout` か `save_failed` とし、実行の状態・終了コード・`error_code`・所要時間・出力のバイト数も入れる。ホストではコマンドが動いたのに結果を保存できなかったことを、監査ログから分かるようにするためである。例外の文言は監査ログに入れず、アプリのログに出す。
7. 監査ログに `finished` を書く。

`started`・`finished` と結果の `command_line` には、手順 2 で本体が組み立てた文字列（プレビューで見せたものと同じ）を入れる。ワーカーを起動できないとき、`harden` で終えたとき、本体の期限でワーカーを kill したときは、ワーカーの応答が無いためである。ワーカーも同じ関数と同じ入力から組み立てるので、文字列は一致する。一致することはテストで確かめ、ワーカーの応答から文字列を受け取ることはしない。

送った文字列が実際に実行されたかどうかは、`command_line` とは別に、結果の `executed` で表す。ワーカーは、SSH でコマンドの実行を要求できたら `executed: true`、その前に終えたら（`invalid_command`・`connect_failed`・`host_key_mismatch`・`auth_failed`・`shell_unavailable`）`executed: false` を返す。ワーカーの応答が無いとき（`worker_unavailable`、本体の期限で kill したときの `timeout`）は NULL（分からない）にする。

### 切り離したタスク

利用者がページを離れたり、前に置いたプロキシが接続を切ったりして要求の処理が取り消されても、実行・保存・監査は最後まで行う。取り消されると、今の `CollectorWorker.request` はワーカーを kill するためである（`plugins/remote.py:199-201`）。

- **参照:** タスクへの強い参照を、アプリが持つ集合（`app.state`）に入れ、終わったら外す。asyncio は走っているタスクを弱い参照でしか持たない。
- **待ち方:** 要求の処理は、期限を持たずに `asyncio.shield` でタスクの完了を待つだけにする。
- **空き:** 空きはタスクの `finally` で返す。
- **例外:** 誰も待っていないタスクの例外を落とさないよう、done callback でログに出す。
- **ワーカーの停止:** タスクの中では、`finally` で必ずワーカーを kill する（2 回呼んでも問題ない）。
- **終了時:** アプリの終了（lifespan の `finally` の先頭、`shutdown_collector_registry` より前。`main.py:186-191`）では、走っているタスクを 10 秒まで待ち、残りを取り消して終わるのを待つ。取り消したときは、ワーカーを止めてから監査ログに `aborted` を書く。分離しないモードで子プロセスを残さないためである。手順 6 の commit が済んでから取り消された場合は、結果は保存されているので `aborted` ではなく `finished` を書く（commit のあとの監査の書き込みは取り消しから守る）。
- **停止の猶予:** 処理中の要求は実行が終わるまで待つので、アプリの停止には最大でおよそ 55 秒に加えて 10 秒かかる。同梱の compose（`docker-compose.postgres.yml`・`docker-compose.sqlite.yml`）は `stop_grace_period` を持たず、Docker の既定の 10 秒で強制終了する。app のサービスに `stop_grace_period: 75s` を足し、運用の文書に停止の猶予を書く。それでも強制終了されたときは、`finished` も `aborted` も無い `started` が残る（7 章）。

### 本体からワーカーへ渡すもの

- 接続先 1 件を、用途を確かめて直接読む関数を新しく書く。`materialize_ssh` は収集の設定のスキーマを前提にするので使わない。
- 分離モードかどうかにかかわらず、鍵と承認したホスト鍵は、ファイルにせず、要求の項目にそのまま入れる。
- 要求は 2 つ送る。先に鍵を含まない `{"op": "harden"}` を送り、ワーカーが自分を dumpable でなくしたことを応答で確かめる。応答は `{"applied": 真偽}` とする。本体は、自分が Linux（`sys.platform.startswith("linux")`）なら `applied` が真であることを必須にし、偽なら `diagnose` を送らずに `worker_unavailable` として終える。Linux 以外では偽を許す。ワーカーには `VEA_PROCESS_NON_DUMPABLE` が渡らないので、この処理は設定によらず常に行う。
- `diagnose` は、`harden` を確かめたのと同じワーカーに送る。今の `CollectorWorker.request()` は要求のたびに `ensure_started()` を呼び（`plugins/remote.py:162-163`）、ワーカーが止まっていれば新しく起動する（同 121-124 行）。新しいプロセスは dumpable が元に戻っているので、前の `applied: true` は当てにならない。そこで `request()` に、止まっていても起動し直さない指定（`auto_start=False`）を足す。止まっていたら要求を送らずに `CollectorWorkerError` を上げる。`diagnose` はこの指定で送り、ワーカーが止まっていたら `worker_unavailable` として終える。今の呼び出し元の挙動は変えない。
- `diagnose` の要求の形: `{"op": "diagnose", "ssh": {"host", "port", "username", "private_key", "host_key"}, "product": "esxi" | "vcenter", "command": {"builtin": ID, "params": {...}} | {"custom": {"template": 雛形, "param_definitions": [{"name", "type"}]}, "params": {...}}, "deadline_seconds": 残りの秒数}`。`params` は、どこでも引数の値（名前から値への対応）を指し、引数の定義は `param_definitions` と呼ぶ。
- モックモードかどうかは本体で決める。モックモードではワーカーを起動せず、組み込みのコマンドにはコマンドごとの固定の出力を、追加のコマンドには「モックモードのため実行していません」の 1 行を返す。どちらも状態は `succeeded`、終了コードは 0 にし、ホストでは実行していないので `executed` は偽にする（ワーカーにはモックモードの値が渡らない）。`command_line` は、本体が同じ関数で組み立てる。シードとスクリーンショットに使う。

### ワーカーの中の処理（`op="diagnose"`）

- `_handle` の中で、`entry_point` を読む前（`worker.py:199` より前）に `harden` と `diagnose` を分ける。プラグインは読み込まない。
- `harden` は `PR_SET_DUMPABLE` を 0 にして `{"applied": true}` を返す。失敗したときと Linux 以外では `{"applied": false}` を返す（Linux 以外で何もしないのは開発の環境で動かすため。Linux 以外は分離モードも無い）。
- known_hosts の行は、ホスト鍵の別名と同じ名前で作る。ポートが 22 なら `host`、それ以外は `[host]:port` とする（`services/ssh_management.py:157` と同じ）。
- 組み込みのコマンドは、ワーカーの側でも同じ一覧（本体のパッケージの `catalog.py`）から引き、引数を確かめ直してから文字列を組み立てる。本体は、組み込みのコマンドについては組み立てた文字列を送らない。ワーカーには `VEA_SSH_ALLOWED_PORTS` が渡らないので、ポートは本体だけが確かめる。追加のコマンドは、本体が雛形・引数の定義・値を送り、ワーカーは同じ関数で雛形と値を確かめ直してから組み立てる。本体は、追加のコマンドについても組み立てた文字列を送らない。ワーカーが確かめ直しで断ったときは、接続せずに `error_code: invalid_command` を返す。本体の確認を通った要求では起きないはずなので、ほかのワーカーの失敗と同じく `error` の結果として保存し、監査ログには `finished` を書く。
- 鍵は `asyncssh.import_private_key`、ホスト鍵は `asyncssh.import_known_hosts` で読み、メモリのまま `asyncssh.connect` に渡す（`known_hosts` に文字列を渡すとファイル名と見なされるので、`SSHKnownHosts` を渡す）。
- 接続は `open_reader` と同じ設定で開く。検証した IP に接続し、ホスト鍵は承認したものだけを受け入れ、パスワード認証・キーボード対話認証・エージェント・SSH の設定ファイルを使わない。接続と認証は 8 秒まで。
- vCenter の前置きは、`_vcenter_shell` と同じ確かめ方で決める。処理はプラグインのパッケージから読まず、本体の `services/diagnostics/ssh.py` に書く。プラグインは本体を import しない約束であり、逆向きに本体がプラグインの内部に頼るのも避けるためである。本体の `pyproject.toml` の依存に asyncssh を直接書く。
- 出力は、標準出力 64 KiB、標準エラー 16 KiB（どちらも UTF-8 に読む前のバイト数）まで保存する。上限を超えたら、超えた分を捨てながら EOF まで読み続ける。読むのをやめると、相手が受信のウィンドウで止まり、終了コードが返らないためである。UTF-8 として読めないバイトは置き換える。
- 時間切れのときも、そこまでの出力と「切った」を返す。
- 失敗の区分は、ワーカーの中で asyncssh の例外から決め、`ok=true` の応答に `error_code` を入れて返す。例外の文言は返さず、ワーカーの stderr にだけ出す（今の扱いと同じ）。

### 失敗の区分

| `error_code` | 決める場所 | 意味 |
|---|---|---|
| `invalid_command` | ワーカー | コマンドの雛形か引数が、ワーカーでの確かめ直しを通らない（接続しない） |
| `connect_failed` | ワーカー | 名前解決・TCP・SSH の接続ができない |
| `host_key_mismatch` | ワーカー | ホスト鍵が承認したものと違う |
| `auth_failed` | ワーカー | 鍵で認証できない（Shell Access が無効なときも含む） |
| `shell_unavailable` | ワーカー | vCenter で Bash を使えない |
| `no_exit_status` | ワーカー | 終了コードが返らない、またはシグナルで終わった |
| `timeout` | ワーカー・本体 | ワーカーの中の期限を超えた。または本体の期限が切れてワーカーを kill した |
| `worker_unavailable` | 本体 | ワーカーを起動できない（`CollectorWorkerServiceError`）、応答が壊れている、ワーカーが落ちた |

## 5. 対応手順

### 同梱する手順

障害パターン 7 種類のそれぞれに、手順を `services/diagnostics/procedures.py` に持つ。手順は、文章の段（step）を並べたもので、各段は使えるコマンドの ID を 0 個以上持つ。コマンドの無い段（「接続先のスイッチポートのログを確認する」など）もある。ESXi の手順の最初の段では、`esxi.hostname` で、接続したホストが目的のホストかを確かめる。

| 障害パターン | 主な段とコマンド |
|---|---|
| `host-conn-flapping`・`host-reconnect-failed` | 管理エージェント（`esxi.hostd`・`esxi.vpxa`）、管理ネットワーク（`esxi.vmk`・`esxi.ping`）、再起動の有無（`esxi.uptime`） |
| `apd-timeout`・`apd-repeated` | パス（`esxi.paths`）、デバイス（`esxi.device`）、アダプタ（`esxi.adapters`）、同じ時間帯のほかのホスト（タイムラインと影響範囲。コマンドなし） |
| `nic-link-flapping` | NIC のリンク（`esxi.nic`）、統計（`esxi.nic-stats`）、スイッチ側のログ（コマンドなし） |
| `ha-failover` | 障害ホストの HA のエージェント（`esxi.fdm`）、再起動とメンテナンスモード（`esxi.uptime`・`esxi.maintenance`）、再起動した VM（タイムライン。コマンドなし） |
| `vmotion-failures` | vMotion の VMkernel（`esxi.vmk`）、移行先への疎通（`esxi.ping`）、失敗したタスクの詳細（案 3a のタスクの結果。コマンドなし） |

手順の文は、組み込みの障害パターンの説明と食い違わないようにする。すべての障害パターンに手順があること、手順が使うコマンドの ID がすべて一覧にあることを、テストで確かめる。

### インシデントへの候補

インシデントの詳細では、次のどちらかに当たる障害パターンの手順を「候補」として先に出す。
- 紐付いた通知の写しで、ルールの種別が `event_pattern` のもの。`context_key` からパターンの ID と対象の moid を取る。
- 紐付いたイベントの写しで、種別がパターンのどれかの段に入っているもの。

候補には、当たった理由（どの通知か、どのイベントか）を添える。実行の画面で対象を先に選んでおくのは、ホストが分かるときだけにする。
- 通知からは、パターンの対象がホストのとき（`ha-failover` 以外）だけ、`(vcenter_id, entity_moid)` を使う。
- イベントからは、写しの対象の種別が `HostSystem` のときだけ、`(vcenter_id, entity_moid)` を使う。
- 照合は `diagnostic_targets` の `(vcenter_id, host_moid)` で行う。クラスタや VM しか分からないときは、先に選ばない。

候補に無い手順も、一覧から選んで開ける。

手順は、機能が無効でも、viewer でも読める。静的な文書だからである。コマンドの「実行」は、機能が有効で admin のときだけ出す。

## 6. API

ルーターは 2 本に分ける。
- **ゲート付き（`/api/diagnostics/...`）:** 機能が無効なら 404。今のプラグイン管理と同じく、ログイン確認より先に評価するようにマウントする（`main.py:331-340` の形）。admin だけが呼べる。入力の誤り（422）の応答にアップロードした秘密鍵が載らないよう、今の SSH の API と同じく `route_class=SafeSetupRoute`（`plugin_setup.py:60-75・84`）を付ける。この設定で入力の形の誤りは処理の前に 422 で返り、監査の `rejected` が残らない。そのため実行の要求の本文は、型だけを pydantic で確かめる。引数の正規表現、コマンドの製品と対象の製品の一致などは、手順 2 で引数の定義（組み込みは一覧、追加はその行）と照らして確かめ、断ったら監査に残す。今の SSH の変更系の API が取る `mutation_gate`（プラグインのレジストリの再読み込みとの排他）は、診断の API では取らない。診断の鍵と接続先は、収集のレジストリから参照されないためである。
- **通常:** 手順と結果を読む API。今の `/api` のルーターに入れ、機能が無効でも使える。

| メソッドとパス | ルーター | ロール | 内容 |
|---|---|---|---|
| `GET /api/event-patterns/procedures` | 通常 | viewer | 同梱の手順の一覧（コマンドの ID と名前つき） |
| `GET /api/incidents/{id}/procedures` | 通常 | viewer | そのインシデントの候補の手順 |
| `GET /api/incidents/{id}/diagnostic-runs/{run_id}` | 通常 | viewer | 1 件の結果の出力。`run_id` は `fits_integer_id` で確かめる |
| `GET /api/diagnostics/commands` | ゲート付き | admin | 組み込みと追加のコマンドの一覧（引数の定義つき）と、引数の種類の一覧 |
| `POST`・`PUT`・`DELETE /api/diagnostics/commands[/{id}]` | ゲート付き | admin | 追加のコマンド。更新と削除は `revision`。雛形の誤りは 422 で、理由の区分と引数の名前を返す（4 章） |
| `GET`・`POST`・`PUT`・`DELETE /api/diagnostics/targets[/{id}]` | ゲート付き | admin | 実行の対象 |
| `GET /api/diagnostics/vcenters/{id}/hosts` | ゲート付き | admin | ESXi の一覧（`plugin_setup.py:642` の処理を切り出して使う） |
| `/api/diagnostics/ssh/credentials`・`/connections`（今の SSH の API と同じ形） | ゲート付き | admin | 用途 `diagnostics` の鍵と接続先 |
| `POST /api/diagnostics/incidents/{id}/runs/preview` | ゲート付き | admin | 送る文字列・接続先・指紋を返す。SSH はしない（4 章） |
| `POST /api/diagnostics/incidents/{id}/runs` | ゲート付き | admin | 実行（4 章） |

- インシデントの詳細（`GET /api/incidents/{id}`）に、結果の一覧（出力を除いた列）を足す。
- `GET /api/config`（`AppConfigResponse`）に `diagnostics_enabled` を足す。
- レート制限（`main.py:108-122`）に足す。`POST /api/diagnostics/ssh/connections/*/host-key` と `GET /api/diagnostics/vcenters/*/hosts` は、今と同じ `probe` の枠で数える。`POST /api/diagnostics/incidents/*/runs` は、専用の枠 `diagnostics` で数える。設定は `RATE_LIMIT_DIAGNOSTICS_PER_MINUTE`（既定 10）で、`main.py:268-276` の対応表に足す。
- 対象や追加のコマンドを消しても、結果は残る（外部キーにしない）。
- 診断用の接続先を削除する API は、今の SSH の API と同じく作らない。対象から使われている接続先は、別の鍵に替えられるが、用途は変えられない。

## 7. 監査記録

`auth/audit.py` の `audit()` で、次の出来事を 1 行ずつ残す。共通の項目は、利用者名・利用者の ID・要求元の IP である。

| `event` | 主な項目 |
|---|---|
| `diagnostics.run.started` | インシデント、対象、接続先（ホスト・ポート・ユーザー名）、コマンドの区分と ID、引数、送るコマンドの文字列 |
| `diagnostics.run.finished` | 上に加えて、状態、`executed`、終了コード、`error_code`、所要時間、出力のバイト数、切ったか |
| `diagnostics.run.rejected` | 断った理由（引数や雛形の誤り、対象と製品の不一致、プレビューのあとの変更、件数の上限、空きが無い、ホスト鍵が未承認など） |
| `diagnostics.run.discarded` | 実行のあとで結果を捨てた理由（インシデントが消えた、件数の上限、保存の時間切れ `save_timeout`、保存の失敗 `save_failed`）。保存の時間切れと失敗では、実行の状態・終了コード・`error_code`・所要時間・出力のバイト数も入れる |
| `diagnostics.run.aborted` | アプリの終了で実行を取り消した |
| `diagnostics.command.created`・`updated`・`deleted` | 名前、製品、雛形、引数の定義 |
| `diagnostics.target.created`・`updated`・`deleted` | vCenter、製品、moid、接続先 |
| `diagnostics.ssh.*` | 鍵の作成・削除、接続先の作成・更新、ホスト鍵の取得・承認（秘密鍵は出さない） |

`finished`・`discarded`・`aborted` のどれも無い `started` は、アプリが強制終了されて途切れたものである。保存の時間切れや DB の失敗では `discarded` を書くので、ここには入らない。

- 出力は監査ログに出さない。
- 監査のロガー（`vcenter_event_assistant.audit`）の水準は、`LOG_LEVEL` にかかわらず INFO に固定する（`logging_config.py`）。今は `LOG_LEVEL=WARNING` にすると監査ログが出なくなる。この変更は認証の監査にも効く。足すのは `"vcenter_event_assistant.audit": {"level": "INFO", "propagate": True}` だけで、ハンドラは付けない（付けると同じ行が 2 回出る）。今のテストは監査のロガーに `caplog` のハンドラを直接付けているので（`tests/test_auth_api.py:102-108`）、影響しない。
- ロールが足りない要求（403）と機能が無効の 404 は、今の認証の監査の扱いに任せ、ここでは足さない。

## 8. 画面

### 診断の設定（PR E）

設定タブに「診断」のサブタブを足す。admin で、機能が有効のときだけ出す。
- **実行の対象:** vCenter を選び、ESXi を一覧から選ぶか vCenter 自身を選んで、診断用の接続先を結び付ける。
- **SSH の鍵と接続先:** 今のプラグインの設定の画面（`PluginSetupPanel.tsx` の `SSHField`）の鍵の生成・アップロード・公開鍵・ホスト鍵の承認を、API のパスと文言を引数にした部品に切り出して使う。依頼文は「ESXi のローカルユーザーに Administrator ロールと Shell Access を与え、公開鍵を登録する」ことを書き、ログの読取権限の文言を使わない。
- **追加のコマンド:** 一覧・追加・変更・削除。追加と変更の画面では、雛形と引数（名前と種類）を入れる。登録を断った理由（定義の無い名前、使われていない引数など）は、その場で出す。読み取り専用かどうかを本体が確かめないことも書く。

### インシデントの詳細（PR F）

- **対応手順:** 候補の手順を先に、ほかの手順を折りたたんで出す。各段の文と、使えるコマンドを並べる。
- **実行:** admin で機能が有効なら、コマンドの横に「実行」を出す。押すと小さな画面で、対象（5 章の条件に合えば先に選んでおく）と引数を入れる。プレビューの API が返した送る文字列と接続先（ホスト名・ユーザー名）をそのまま見せてから実行し、実行の要求には返った指紋を入れる。対象か引数を変えたら、プレビューを取り直す。追加のコマンドは、手順の外の「ほかのコマンド」から選ぶ。引数があれば、組み込みと同じく値を入れる。409（`diagnostic_changed`）が返ったら、プレビューを取り直して見せ直す。
- **待ち:** 実行には最大でおよそ 55 秒かかる。失敗の表示のあとに詳細を読み直し、要求が途中で切れても保存された結果を出す。
- **結果:** 「診断の結果」の欄に、時刻・コマンド・対象・状態・終了コード・実行した人を並べる。行を開くと出力を読み込んで、等幅で見せる。切ったときはその旨を出す。
- **経過:** `diagnostic` の行を、ほかの自動の記録と同じ見た目で出す。

## 9. PR の分け方

### PR A: 本書

本書と、10 案の文書の更新（2 章の表の #9 に本書へのリンクを足す）。

### PR B: SSH の用途の分離と診断の設定

- 移行（1 本）: `ssh_credentials.purpose`・`ssh_connections.purpose`（3 章の移行の書き方）、`diagnostic_targets`、`diagnostic_commands`。移行のテストの名前には `diagnostic` を入れる。
- `VEA_DIAGNOSTICS_ENABLED`（既定 `false`）、認証が無効のときの起動時の拒否、ゲート、`AppConfigResponse` の `diagnostics_enabled`。
- 今の SSH の API と、`reference_digest`・`materialize_ssh` で、用途 `logs` に絞る。SSH の処理の切り出し。
- 診断の SSH・対象・追加のコマンドの API、ESXi の一覧の切り出し、レート制限。設定の変更の監査ログ。監査のロガーの水準の固定。
- `services/diagnostics/catalog.py` のうち、引数の種類の一覧と、雛形の確認・組み立ての関数。追加のコマンドの登録で使うためである。組み込みのコマンドの一覧は PR C で足す。PR B の `GET /api/diagnostics/commands` は、追加のコマンドと引数の種類の一覧を返し、組み込みのコマンドは空にする。
- テスト:
  - 用途をまたいだ参照を、すべての経路で断ること（両方向）。経路は、1 章に挙げた `reference_digest`・`materialize_ssh` の呼び出し元ごと（設定の検証・テスト・適用、有効への切り替え、setup の実行、定期の収集）と、鍵と接続先の API のそれぞれ。
  - 今の収集の設定がそのまま動くこと。移行のあと、今ある鍵と接続先が `logs` になること。
  - 無効のときの 404 がログイン確認より先に返ること、admin 以外の 403、認証が無効のときの起動時の拒否。
  - 楽観ロック、対象の CHECK と 2 つの一意制約。
  - 追加のコマンドの雛形の登録の確認（`tests/test_diagnostics_catalog.py`）。断るもの: 定義の無い名前、`{{Vmk}}` のような打ち間違い、使われていない引数、直前が `$` か `\` の差し込み口（`${{x}}`・`"${{x}}"`・`$'\{{x}}'`）、名前の重なり、形の誤った名前、一覧に無い種類、9 個以上の引数、制御文字。それぞれ理由の区分が返ること。通すもの: 差し込み口の無い雛形、`awk '{print $1}'` のような `{{名前}}` の形に当たらない波かっこ、オプションやパスの中の差し込み口（`--nic-name={{vmnic}}`）。
  - 引数の種類の性質: どの種類も、通る値の例のすべてで、正規化した値が空でなく、`[A-Za-z0-9@%+=:,./_-]` だけからなり、先頭が英数字で、`shlex.quote` が値を変えないこと。種類の一覧の全件を回すテストにして、種類を足したときに自動で対象になるようにする。
  - 引用符の中、`"$(...)"` の中、`$'...'` の中（手前にエスケープの無い位置）、`'a {{x}} b'` のように大きな語の一部に置いた差し込み口でも、組み立てた文字列を bash と sh で実行したとき、値がそのままの文字として渡ること（展開・分割・引用の外しが起きない。シェルの無い環境では飛ばす）。直前が `$` か `\` の差し込み口（`${{x}}`・`$'\{{x}}'`・`\{{x}}`）は登録で断ること。
  - 形の誤った鍵のアップロード（`name` が無いなど）で、422 の応答に秘密鍵が出ないこと。
  - `LOG_LEVEL=WARNING` でも監査ログが出ること。
  - PostgreSQL でも、移行・CHECK・一意制約を流す。`ci.yml` の「Verify event entity, log pattern, and incident migrations」（移行のテスト、214-217 行）と「Verify timeline filtering, patterns, config changes, inventory, and incidents」（221-227 行）の両方の `-k` に `diagnostic` を足し、新しいテストのファイルを後者の一覧に足す。
- 文書: `docs/operations/backend-operations.md`（設定、認証が必須なこと）、`docs/operations/collector-plugins.md`（分離モードの節に、ワーカーへ診断の鍵も渡ることを足す）、`.env.example`、`docs/features/features_list.md`（表）。

### PR C: 診断コマンドの実行

- 組み込みの一覧、ワーカーの `op="harden"` と `op="diagnose"`、ワーカーのサービスの起動時の `PR_SET_DUMPABLE`、本体の SSH の処理、切り離したタスク、プレビューの API（`runs/preview`）と指紋、実行の API と流れ、結果の表（移行 1 本）、経過の種類 `diagnostic`（バックエンドと、画面の zod の `EntryKind` の両方。画面の変更がないと、`diagnostic` の行ができた時点でインシデントの詳細を読めなくなる）、出力の API、監査ログ、モックモード、本体の依存への asyncssh の追加。
- テスト（`tests/test_diagnostics_catalog.py`・`tests/test_diagnostics_worker.py`・`tests/test_diagnostics_runs_api.py`、結合テストは `tests/test_diagnostics_ssh_integration.py`）:
  - 一覧の各コマンドの文字列の組み立てと、引数の拒否（`;`・空白・末尾の改行・先頭の `-`・IPv6・スコープ ID を含む値など）。
  - 組み込みのコマンドの雛形が、すべて雛形の確認を通ること。
  - 追加のコマンドの文字列の組み立てと、引数の拒否（組み込みと同じ値の一覧）。
  - ワーカーの側での確かめ直し（組み込みと追加の両方で、本体の確認を通っていない要求を断り、`invalid_command` を返して接続しない）。
  - プレビューと実行で同じ文字列と指紋になること。プレビューのあとでコマンド・対象・接続先を変えたときの 409（`diagnostic_changed`）と、監査の `rejected`。プレビューでは監査ログを書かないこと。
  - 鍵を一時ファイルに書かないこと。`harden` の応答の前に `diagnose` を送らないこと、`prctl` に失敗したら `diagnose` を送らないこと。
  - `harden` の応答のあとでワーカーが止まったら、新しいワーカーを起動せず、`diagnose` も送らずに `worker_unavailable` になること（分離するモードとしないモードの両方）。`auto_start` を指定しない今の呼び出しでは、これまでどおり起動し直すこと。
  - ワーカーと本体の組み立てた文字列が、組み込みの全件と追加のコマンドの例で一致すること。ワーカーの応答が無い失敗（起動できない、`harden` で終えた、本体の期限で kill した）でも、結果と監査ログに本体の組み立てた文字列が入り、`executed` が NULL になること。接続や認証の失敗では `executed` が偽になること。
  - ポートが 22 以外の接続先で、ホスト鍵の照合が通ること。
  - 出力の切り詰め（上限を超えても終了コードが返ること）、時間切れで途中までの出力が残ること、失敗の区分、文言を出さないこと。
  - 件数の上限（手順 2 と手順 6 の両方）、空きが無いときの 409、インシデントが途中で消えたとき。
  - 保存が 10 秒を超えたとき、DB の書き込みや commit が失敗したときに、巻き戻して 503（`diagnostic_save_failed`）を返し、監査ログに理由と実行の状態つきの `discarded` が書かれ、空きが返ること。
  - 実行中に DB の接続を持っていないこと。要求が取り消されても結果と監査ログが残ること。アプリの終了で取り消したときに、空きが返り、`aborted` が書かれること。
  - ワーカーの中の時間切れで、途中までの出力が本体まで届くこと。Linux で `harden` が `applied: false` を返したら `diagnose` を送らないこと。
  - 新しいテストのファイルを、`ci.yml` の「Verify timeline filtering, patterns, config changes, inventory, and incidents」の一覧に足す。
  - SSH の部分は、偽の接続でテストする。asyncssh のテスト用のサーバーを使う結合テストを 1 本置き、Claude の側で流す（Codex のサンドボックスでは SSH のテストが落ちるため）。
  - PostgreSQL でも結果の表と CASCADE を流す（テストの名前に `diagnostic` と `postgres` を入れる。`-k` は PR B で足してある）。
- compose の app のサービスに `stop_grace_period: 75s` を足す。
- 文書: 運用の文書（安全の考え方、監査ログ、上限、待ち時間、停止の猶予）。

### PR D: 対応手順

- 同梱の手順、手順の一覧の API、インシデントの候補の API。
- テスト（`tests/test_diagnostics_procedures.py`）: すべての障害パターンに手順があること、コマンドの ID がすべてあること、通知とイベントの両方から候補が出ること、moid の取り出しと、ホストのときだけ先に選ぶこと、候補が無いとき。

### PR E: 画面（診断の設定）

- 設定のサブタブ、SSH の部品の切り出し（プラグインの設定の画面の挙動を変えない）、対象と追加のコマンドの画面、zod のスキーマ。
- スクリーンショット（明暗の両方）。

### PR F: 画面（インシデントの手順・実行・結果）と文書

- インシデントの詳細の手順・実行の小さな画面・結果・経過の表示、シード（対象の `host_moid` はモックの ESXi の一覧の `mock-esxi` に合わせる。プレビューの指紋に承認したホスト鍵を使うので、ホスト鍵を承認済みにした診断用の鍵と接続先も入れる）。
- ユーザーガイド `docs/userguide/diagnostics.md` を新しく作る（admin の準備: 診断用のアカウントと Shell Access、鍵の登録、ホスト鍵の承認、`VEA_DIAGNOSTICS_ENABLED`、2 章の安全の考え方、対象と接続先の取り違えに注意すること）。`incidents.md` から案内する。アプリ内ヘルプ、CHANGELOG。
- スクリーンショット（明暗の両方）。

## 10. 個人に関する情報と保存の期間

| 情報 | 入る場所 |
|---|---|
| 実行した人、設定を変えた人の名前 | 結果、経過、対象、追加のコマンド、監査ログ |
| SSH のユーザー名とホスト名 | 結果の写し、監査ログ |
| コマンドの出力（ホスト名・IP アドレス・WWN・利用者名などを含むことがある） | 結果 |

- **画面:** 結果は、インシデントと同じく viewer も含めて全員が読める。
- **チャット（LLM）と案 10 の出力:** 入れない。インシデントの中身をどちらにも入れていないためである。匿名化（名前だけを扱う）は出力の IP アドレスなどを伏せられないので、後続でチャットに入れるときは別に決める。
- **保存の期間:** 結果はインシデントと一緒に、解決から `INCIDENT_RETENTION_DAYS`（既定 90 日）で消える。解決したあとに実行しても、期間は延びない。admin はインシデントごと消せる。結果を 1 件ずつ消す API は作らない。監査ログは、ログの保存の設定に従う。

## 11. 範囲外（後続）

- 運用者が手順を書くこと（今は種別のガイドの「対処」を使う）。
- 何でも入る文字列の引数と、空白や引用符の要る種類（4 章）。必要になったら、値を雛形に差し込まず、コマンドの前で環境変数に入れて本文から `"$名前"` で参照する形など、別の仕組みを決める。
- IPv6 の疎通の確認（`vmkping -6`）。
- タイムラインの障害パターンのカードから手順を開くこと。
- 結果をチャット（LLM）に渡すこと、案 10 の出力に入れること。
- 複数のホストへの一括の実行、定期の実行。
- 手順の中で、前の段の出力やイベントの内容から次の段の引数を埋めること。そうすると値を入れるのが admin でなくなるので、差し込み口を置ける位置（コマンドの名前の位置、`${...}` と `$((...))` の中、`$'...'` の中のエスケープの直後）を、そのときに決め直す（4 章）。
- `authorized_keys` の制限など、対象側の対策を自動で設定すること。

## 12. リスク

- **コマンドの確認:** 組み込みのコマンドは、2026-11-26 に利用者が実機（ESXi 8.0.3、vCenter 8.0）で実行した結果で確かめた（4 章）。確かめていないのは、`esxi.fdm` の HA が有効なときの出力、`esxi.device` の成功したときの出力、vCenter の appliance shell を経由する経路の 3 つである。`esxi.fdm` は利用者の判断で一覧に入れる。`esxi.device` は PR F の撮影の前に確かめ、形が想定と違えば説明を直す。
- **admin の乗っ取り:** admin のアカウントが乗っ取られると、Administrator ロールのアカウントでホストにコマンドを送られる。追加のコマンドがあるので、実質的にホストを操作できる。既定で無効にし、監査ログを残し、運用側の対策（2 章）を文書に書く。
- **プラグインのワーカー:** 同じ UID で動く悪意のあるプラグインは、診断のワーカーと、要求を中継するワーカーのサービスに干渉できる。鍵をファイルにせず、`PR_SET_DUMPABLE` を 0 にしても、なくせない（2 章）。
- **待ち時間:** 実行の要求は最大でおよそ 55 秒（SSH の 45 秒と保存の 10 秒）かかる。前に置いたプロキシの時間切れがそれより短いと、画面には失敗と出る。結果は切り離したタスクで保存するので、画面は詳細を読み直して出す。
- **対象の取り違え:** `host_moid` と接続先が同じホストを指すかは、本体では確かめない。手順の最初に `esxi.hostname` を置き、実行の画面に接続先を出して、取り違えに気づけるようにする。
- **大きさ:** 結果の出力で、インシデントの行は最大でおよそ 8 MiB 増える。詳細の API は出力を返さないので、画面の読み込みは重くならない。
- **出力の中身:** 出力に IP アドレスや WWN などが入る。viewer も読めるので、文書に書く。
