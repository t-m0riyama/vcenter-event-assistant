# 2026-10 セキュリティ監査の残りの対応

最終更新: 2026-10-09（PR1・PR2 マージ済み。PR3a は PR #273 でレビュー中。6 回目の指摘 2 件に対応し、再レビューを待つところ）

## Context

`docs/security-audit-report-2026-10-05.md` の指摘（Issue #235〜#241）は、認証機能の計画（`2026-10-08-auth-local-ad-ldap.md`）を優先したので手つかずだった。認証の全 PR がマージされたので、オープンな Issue #235 以降を、今のコードと認証の追加による前提の変化に照らして見直し、対応の要否・方法・優先度を決めた。

決定事項（利用者の確認済み）:
- リリースの前に Issue #236・#238・#239・#235・#237 まで入れる
- `SMTP_TLS_VERIFY=false` は本番でも禁止しない。起動時に WARNING を出すだけにする

## 進捗

| PR | 内容 | Issue | 状態 |
|---|---|---|---|
| 1 | SMTP の STARTTLS で証明書を検証する | Issue #236 | マージ済み [PR #271](https://github.com/t-m0riyama/vcenter-event-assistant/pull/271)（Codex のレビューで指摘なし） |
| 2 | CSV の数式インジェクション対策、アップロードの一時ディレクトリの削除 | Issue #238・Issue #239 | マージ済み [PR #272](https://github.com/t-m0riyama/vcenter-event-assistant/pull/272)（Codex の指摘 1 件（改行と全角の記号）に対応し、再レビューで指摘なし） |
| 3a | プラグインの子プロセスに渡す環境変数を許可リストにする | Issue #235 | レビュー中 [PR #273](https://github.com/t-m0riyama/vcenter-event-assistant/pull/273)（Codex のレビュー 6 回。指摘 8 件に対応した（うち 1 件は制約としてドキュメントに書いた）。下の「PR3a のレビューの経過」） |
| 3b | Docker イメージで `/app` を root 所有にする、脅威モデルのドキュメント | Issue #235 | 未着手 |
| 4 | SSH 接続先の名前解決後の検証、probe 系 API の rate limit | Issue #237 | 未着手 |
| ― | リリース（認証機能のアップグレードの注意と SMTP の検証の注意をリリースノートに書く） | ― | 未着手 |

各 PR は単独でマージでき、テストが通る状態にする。Codex のレビューは今までと同じ進め方（PR 作成時に自動。直したら「@codex review」に観点を添えて依頼）。

## 現状と判断

| Issue | 今のコード | 認証の追加による変化 | 判断 |
|---|---|---|---|
| Issue #235 M-1 権限分離 | 一部だけ対応済み。`plugins/subprocess_env.py` の `child_process_env()` は bootstrap パスワードだけを除き、`VEA_SECRET_KEY`・`DATABASE_URL`・LLM の API キー・`SMTP_PASSWORD` は渡す。Dockerfile は `/app` を `appuser` 所有のまま `uv sync` を実行する | 変わらない。DB に書けるプラグインは admin のセッションも作れるので、影響はむしろ大きい | 対応する（中） |
| Issue #236 M-2 SMTP | `email_channel.py` の `server.starttls()` に context がない（`CERT_NONE`） | 関係しない | 対応する（高） |
| Issue #237 M-3 SSRF | `plugin_setup.py` が `resolve_dns=False` のまま。rate limit は `main.py` の `_RATE_LIMITED_POST_PATHS` の完全一致だけ | 使えるのが admin に限られた | 対応する（中） |
| Issue #238 M-4 CSV | `log_export.csv_row` と `metricCsv.escapeCsvField` とも数式を無害化しない | viewer 以上のログインが必要になった。ログには外部から文字列を入れられるので、危険度は変わらない | 対応する（高） |
| Issue #239 L-1 一時ファイル | `api/routes/plugins.py` の `install_from_upload` の `mkdtemp` を消さない（`installer.py` が消すのは自分の staging だけ） | admin に限られた | 対応する（高。小さい） |
| Issue #240 L-2 秘密値 | 未対応 | admin に限られた | 保留（秘密値を持つプラグインが出てきたら） |
| Issue #241 L-3 インデックス | 未対応 | 既定で無効のうえ、admin に限られた | 保留（一部だけ、必要になったら） |
| Issue #251 独自 OID の DN | 対応しない方針 | ― | 開けたまま |
| Issue #266 Samba の `DOMAIN\user` | 拒否する側に倒れる。ユーザーガイドに制約として書いた | ― | 保留（求められたら） |

## PR1: SMTP の証明書の検証（Issue #236）

- `services/alerting/notification/email_channel.py` の `_send_smtp_message` で、`ssl.create_default_context(cafile=settings.smtp_ca_bundle)` を作り `starttls(context=...)` に渡す。検証しないときは `check_hostname=False`・`CERT_NONE` の context を明示する
- `settings.py` の SMTP の設定に追加する（`smtp_use_tls` の近く。名前は既存の `SMTP_*` に揃える）
  - `smtp_ca_bundle`（`SMTP_CA_BUNDLE`）: 社内 CA のファイルのパス。指定してファイルがなければ起動時に検証エラー
  - `smtp_tls_verify`（`SMTP_TLS_VERIFY`、既定 true）: false なら起動時に WARNING を出す。本番でも禁止しない（利用者の判断）
- 暗黙の TLS（465 番、`SMTP_SSL`）は今回は入れない
- 証明書の検証の失敗は、今の配信失敗の扱い（outbox・`NotificationDeliveryOutcome`）に乗せ、ログに理由（`ssl.SSLCertVerificationError`）が出るようにする
- テスト: 渡す context の中身（`CERT_REQUIRED`・`check_hostname`・cafile）を `smtplib.SMTP` を差し替えて確かめる。検証の失敗が配信失敗として記録されること
- ドキュメント: `.env.example`、SMTP の設定を説明しているユーザーガイド・運用ドキュメント。リリースノートで「自己署名の SMTP ではアップグレード後に通知が止まる。`SMTP_CA_BUNDLE` か `SMTP_TLS_VERIFY=false` を設定する」と周知する

## PR2: CSV の数式インジェクションと一時ディレクトリ（Issue #238・Issue #239）

### CSV（Issue #238）
- OWASP の対策に従い、文字列の値の先頭が `=` `+` `-` `@` TAB CR なら先頭に `'` を付ける。数値の列（`String(p.value)` など）は対象外
- バックエンド: `services/log_export.py` に共通関数を置き、`csv_row` で文字列の列に使う
- フロント: `frontend/src/metrics/metricCsv.ts` の `escapeCsvField` に入れる（`events/eventCsv.ts`・`events/eventRowToCsv.ts` も同じ関数を通す）。数値を文字列として渡している箇所が無害化されないことを確かめる
- テスト: pytest と vitest で、各記号で始まる値・負の数（数値の列）・普通の値

### 一時ディレクトリ（Issue #239）
- `install_from_upload` の `staging_dir` を、インストールのジョブが終わったとき（成功・失敗とも）と、`start_install` が例外を投げたときに `shutil.rmtree(..., ignore_errors=True)` で消す。ジョブはバックグラウンドで続くので、消す場所はジョブの `finally`（`start_install` に後始末の対象を渡す）
- 起動時に `vea-plugin-upload-*` を `tempfile.gettempdir()` から掃除する。名前にプロセス ID を入れ（`vea-plugin-upload-<pid>-*`）、そのプロセスが終了していれば消す（`services/ssh_management.cleanup_stale_ssh_files` と同じ考え方）。プロセス ID のない以前の形式は、作成から 1 日たったものだけ消す
- テスト: 成功・失敗・`start_install` の例外のそれぞれで、ディレクトリが残らないこと

## PR3a: 子プロセスの環境変数を許可リストにする（Issue #235）

実装（PR #273）:

- `plugins/subprocess_env.py`: 除外リスト（`child_process_env`）をやめ、許可リストにした
  - `worker_env(settings)`（ワーカーと検出用のワーカー。呼び出し元は `plugins/remote.py` の 2 か所）
    - 実行環境: `PATH`・`HOME`・`LANG`・`LC_*`・`TZ`・`TMPDIR`・`SSL_CERT_FILE` などの証明書の場所・`NO_PROXY`・`VIRTUAL_ENV`・`PYTHONPATH` など
    - ワーカーが Settings で読む値: `LOG_LEVEL`・`VEA_COLLECTOR_WORKER_LOG_LEVEL`・`VCENTER_ALLOWED_HOST_SUFFIXES`。`.env` の値は `os.environ` に入らないので、親の Settings から取り出して渡す
    - `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH`（カンマ区切り）に書いた名前の変数。プラグインが独自の環境変数（機密値など）を読む場合に使う
    - プラグインの設定 `VEA_COLLECTOR__<ID>__*` は渡さない。本体が解決して要求の `context.config` で渡すので、ワーカーには要らない（Issue の本文の `VEA_COLLECTOR_<ID>_*` は誤り）
  - `installer_env(with_credentials=...)`（`plugins/installer.py` の `_run_install`）: 実行環境と、資格情報を含まない uv の変数（`UV_CACHE_DIR`・`UV_NATIVE_TLS`・`UV_HTTP_TIMEOUT` など、1 つずつ許可）だけを渡す。`UV_INDEX_URL`・`UV_DEFAULT_INDEX`・`UV_INDEX_<名前>_PASSWORD`・`PIP_INDEX_URL` などは渡さない。インデックスは `VEA_PLUGIN_INDEX_URL` で指定する
  - プロキシ（`HTTP(S)_PROXY`・`ALL_PROXY`、小文字も）は、資格情報を含まなければ渡す。資格情報付き（`url_has_credentials`: 値に `@` があれば資格情報ありとみなす。誤判定は安全側に倒れる）は、ワーカーには passthrough に書いたときだけ、インストーラには `--no-build` のときだけ渡す
- 子プロセスの Settings は `.env` を読まない（`VEA_SETTINGS_IGNORE_DOTENV=1`、`settings._settings_env_file`）
- `installer._install_command`: インデックスかプロキシに資格情報があるときは `--no-build` で wheel だけを入れる。sdist のビルドのコードは、uv のコマンドライン（`/proc/<pid>/cmdline`）と環境変数を読めるため。その場合、アップロードした sdist はインデックスを使わずに入れる（`--no-index --no-deps`、依存は解決されない）。インデックスからのインストールを許可しているときは、アップロードの依存も `VEA_PLUGIN_INDEX_URL` から解決する（今までは渡しておらず、uv の既定のインデックスを使っていた）
- `process_hardening.py`（起動時に `main.lifespan` から呼ぶ）
  - `harden_process`: Linux で本体のプロセスを `prctl(PR_SET_DUMPABLE, 0)` にする。同じ UID のワーカーから `/proc/<pid>/environ` やメモリを読めなくなる。コアダンプが出なくなり、root 以外のデバッガ（py-spy など）も接続できなくなるので、`VEA_PROCESS_NON_DUMPABLE`（既定 `true`）で切れる
  - `warn_if_parent_keeps_secrets`: 親プロセスが同じ UID で、秘密らしい名前の環境変数を持っていれば WARNING を出す（値は出さない）。`uv run` や同じ UID のプロセス管理ツールから起動すると、親が起動時の環境を持ったまま残り、ワーカーが `/proc/<親>/environ` を読めるため。Docker イメージは exec で起動するので影響しない
- ドキュメント: `docs/collector-plugins.md`（「プロセス分離」「動的インストール」）、`docs/backend-operations.md`（設定の一覧、4.1、アップグレードの注意の 4.2 の 7）、`docs/getting-started.md`（`uv run` は開発用）、`.env.example`
- 現在のバージョンの制約（ドキュメントに書いた。利用者の判断）: インストールの間、uv が使う資格情報（インデックスとプロキシ）は uv のコマンドラインと環境変数に載り、既に動いているワーカーが `/proc/<uv の pid>/` から読める。同じ UID では防げないので、資格情報の要らない社内ミラーを勧め、将来、インストーラやワーカーを別の UID に分けることを検討する

### PR3a のレビューの経過

- Codex のレビューは 6 回（`e1d209c`〜`20d7a13`）
  - `e1d209c`: 資格情報付きのインデックスで、アップロードした sdist にも `--no-build` が付いて必ず失敗する（P2）→ `1a58692` でオフラインの経路に
  - `1a58692`: 資格情報付きのプロキシが子プロセスに渡る（P1）→ `aeb2c47` で対応。インストール中に uv の `/proc/<pid>/cmdline`・`environ` を既存のワーカーが読める（P1）→ 同じ UID では防げないので、制約としてドキュメントに書いた
  - `aeb2c47`: スキームのないプロキシ（`user:pass@proxy:8080`）の資格情報を見逃す（P1）→ `6d01825`
  - `6d01825`: ホストの後ろにパスがあると見逃す（P1）→ `2bc79b0` で「`@` があれば資格情報あり」に単純化
  - `2bc79b0`: `uv run` などの親プロセスが秘密を持ったまま残る（P1）→ `20d7a13` で起動時の警告とドキュメント
  - `20d7a13`: 下の 2 件（P2）→ 利用者の判断で両方直した（7 回目の再レビューを依頼する）
- 指摘への対応の繰り返しは、利用者の判断で `20d7a13` で区切った。7 回目の再レビューで P2 以下の指摘が出たら、制約としてドキュメントに書いてマージする
- `20d7a13` の指摘（どちらも P2）と対応
  1. `process_hardening.py:27`: 親プロセスの秘密の名前を探す正規表現が大文字だけを見る。Settings は大文字と小文字を区別しないので、`database_url` などの小文字の名前では警告が出ない。見立て: 妥当。正規表現で大文字と小文字を区別しないようにすれば数行で直る。→ `re.IGNORECASE` を付け、小文字の名前のテストを足した
  2. `process_hardening.py:77`: 対話シェルから `.venv/bin/vcenter-event-assistant` を実行してもシェルは置き換わらない。警告とドキュメントでは `exec .venv/bin/vcenter-event-assistant` と明示すべき。見立て: おおむね妥当（シェルの起動後に `export` した値は `/proc/<pid>/environ` に載らないが、起動時から持つ秘密は載る）。警告の文言と 3 つのドキュメントの例を書き換える。→ 警告と `docs/collector-plugins.md`・`docs/backend-operations.md`・`docs/getting-started.md` の例を `exec .venv/bin/vcenter-event-assistant` にした
- 引き継ぎのメモは PR #273 のコメントにも書いた

## PR3b: Docker イメージと脅威モデル（Issue #235）

- `Dockerfile`: `uv sync --frozen --no-dev` を root で実行してから `USER appuser` に切り替える。`/app` は root 所有で `appuser` は書けない。`appuser` が書けるのは `/data`（DB・プラグインの `VEA_PLUGIN_DIR=/data/plugins`）と `/var/log/vea` だけ
  - `uv` が実行時に `.venv` や `/app` のキャッシュへ書かないこと（起動コマンドが `uv run` なら `--no-sync` などが要るか）を確かめる
  - compose（`docker-compose.sqlite.yml`・`docker-compose.postgres.yml`）でビルドして起動し、プラグインのインストール・収集が動くことを確かめる
- `docs/collector-plugins.md` に脅威モデルを書く
  - プラグインは本体と同じ UID で動く。プロセスの分離はハングを打ち切るためのもので、セキュリティの境界ではない
  - 3a で鍵と DB の資格情報は渡さないが、SQLite の DB ファイル（`/data/vea.db`）は同じ UID なので直接読み書きできる。PostgreSQL なら資格情報がない限り DB に入れない
  - インストールするプラグインは信頼できるものだけにする
  - PR3a で書いた「プロセス分離」の内容（渡す環境変数、`prctl`、現在のバージョンの制約、exec での起動）と合わせて、ひとつの脅威モデルにまとめる
- 別の UID でワーカーを動かす・read-only rootfs は、本体を root で起動して権限を落とす仕組みが要り、変更が大きいので今回はしない。PR3a のレビューで、同じ UID では防げないもの（インストール中の uv の資格情報、起動した親プロセスの環境変数）がはっきりしたので、将来の分離の検討の材料にする。Issue #235 には残りとして書き、閉じるか開けたままにするかはこの PR のときに決める

## PR4: SSRF と rate limit（Issue #237）

- SSH の接続先は、名前解決して検証した IP に接続する（`services/vcenter_host_validation.validate_vcenter_host(..., resolve_dns=True)` と同じ判定）。検証の後に名前で接続すると、もう一度名前解決が起き、DNS の応答を操作できる攻撃者は、検証にはグローバルな IP、接続にはループバックを返せる（DNS rebinding。PR #270 の Codex レビューの指摘）
  - 拒否するもの: ループバック・リンクローカル・メタデータ・マルチキャスト・予約済み・未指定。RFC1918 は今と同じく許す
  - ホスト鍵の照合は元のホスト名で行う。asyncssh の `host_key_alias` にホスト名を渡し、接続先には検証した IP を渡す（known_hosts の行はホスト名のまま使える）
  - 本体の経路: `api/routes/plugin_setup.py` の host-key の probe（`asyncssh.get_server_host_key`）・セットアップのアクション・ホストの一覧
  - ワーカーの経路: 同梱のプラグイン `packages/remote-log-collector` の `transport.open_reader`（`asyncssh.connect`）。ワーカーの中で名前解決して検証し、その IP に接続する（本体で解決した IP を渡しても、収集までの間に DNS が変わるので、接続する側で解決と検証を 1 回で済ませるのが確実）。判定は本体の関数を使えないので、プラグイン API のパッケージに置くか、プラグインの中に持つかは実装時に決める
  - 第三者のプラグインが自分で接続する経路は強制できない。PR3b の脅威モデルに書く
- ポート: 設定で許すポートを絞れるようにする。既定は制限なし（既定を 22 だけにすると既存の設定が壊れ得るため）
- rate limit: `main.py` の `RateLimitMiddleware` の照合を、完全一致に加えてパターン（パスの部品の一致）にも対応させ、`/api/plugins/ssh/connections/*/host-key`・`/api/plugins/collectors/*/draft/actions/*`・`/api/vcenters/*/hosts` を加える。GET が対象なら、メソッドの条件も見直す。バケットは既存の `plugins` を使うか、新しく設けるかは実装時に決める
- テスト: ループバックに解決されるホスト名（名前解決を差し替える）を拒否すること、RFC1918 は通ること、1 回目と 2 回目で名前解決の答えが変わっても検証した IP に接続すること（asyncssh に渡す引数で確かめる）、`host_key_alias` にホスト名が渡ること、パターンの rate limit が効くこと（`VEA_PYTEST=1` で無効になる点に注意し、テストでは有効にする）

## 保留（必要になったら）

- Issue #240 秘密値: スキーマに `x-vea-secret` を足し、暗号化して保存し、応答ではマスクし、`draft/import` では写さない。スキーマ・DB・API・画面にまたがる機能の追加になる。秘密値を持つプラグインが出てきたら対応する（今の SSH 鍵は別の暗号化した列で扱っている）
- Issue #241 インデックス: 入れるなら配布物名の許可リスト（`VEA_PLUGIN_ALLOWED_DISTRIBUTIONS`）と、社内ミラー（`VEA_PLUGIN_INDEX_URL`）を勧めるドキュメント。`--require-hashes` は選べる形にとどめる（必須にすると使い勝手が大きく落ちる）
- Issue #266 Samba の `DOMAIN\user`: 求められたら、構成パーティションの crossRef の NetBIOS 名で照合する案を `tests/manual/directory-lab/` で確かめる。Windows の AD では未確認
- Issue #251 独自 OID の DN: 対応しない。開けたまま

## 確認方法

- 各 PR: `uv run pytest -n auto`、ruff、mypy。フロントを変えた PR は `cd frontend && npm test`（UI を変えたら `npm run build` の後に `npm run e2e`）
- ruff format をリポジトリ全体にかけない（88 桁にそろえていない）
- 修正のたびに、追加したテストが修正前のコードで失敗することを確かめる
- PR1: 自己署名の SMTP（例: ローカルの SMTP のコンテナ）に、CA なしでは失敗し、`SMTP_CA_BUNDLE` か `SMTP_TLS_VERIFY=false` で送れること
- PR2: 書き出した CSV を表計算ソフトで開き、`=HYPERLINK(...)` が文字列として表示されること
- PR3a: ワーカーの中から環境変数を出力するテスト用プラグインで、秘密の値が見えないこと（`test_worker_does_not_see_parent_secrets`）。Linux で `/proc/<親の pid>/environ` を読めないこと
  - Linux 専用のテスト（`prctl`、親プロセスの警告）は macOS でスキップされる。`python:3.12-slim` のコンテナに、`.venv` を除いてリポジトリをコピーし（`tar --exclude=./.venv`）、`UV_PROJECT_ENVIRONMENT=/tmp/venv` で `uv sync --frozen` する。そのうえで、root 以外のユーザーとして `tests/test_plugin_subprocess_env.py` を実行する（root はパーミッションを無視するので確かめられない）
  - 同じ方法で、`uv run` から起動すると親プロセスの警告が出て、`exec` で起動すると出ないことを確かめた
- PR3b: コンテナの中で `appuser` として `/app` に書けないこと。プラグインのインストール・収集が動くこと
- PR4: ループバックに解決されるホスト名で probe が拒否されること、繰り返し呼ぶと 429 になること

## リスク

- PR1 で、自己署名の SMTP を使っている環境はアップグレード後に通知が止まる。リリースノートで周知する
- PR3a の `PR_SET_DUMPABLE` は Linux だけ。macOS の開発環境では効かない
- PR3a の `--no-build` で、資格情報のあるインデックスやプロキシからは sdist しかないプラグインを入れられなくなる。wheel を用意するか、アップロードで入れる（アップロードした sdist の依存は解決されない）
- PR3a で、独自の環境変数を読むプラグインは `VEA_PLUGIN_WORKER_ENV_PASSTHROUGH` に名前を書かないと値を受け取れなくなる。`UV_INDEX_URL` などの uv の環境変数も効かなくなる。アップグレードの注意（`docs/backend-operations.md` の 4.2 の 7）に書いた
- `uv run` や同じ UID のプロセス管理ツールから起動すると、親プロセスの環境変数がプラグインから読める。本番は exec で起動する（Docker イメージは影響なし）
- PR3b の変更は compose の利用者に影響する。ボリュームの所有者が変わらないことを確かめる
