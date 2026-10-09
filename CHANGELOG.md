# 変更履歴

このファイルには、リリースごとの主な変更と、更新するときの注意を書く。版は [Semantic Versioning](https://semver.org/lang/ja/) に従う（1.0.0 より前は、互換性のない変更でも minor を上げる）。

同梱のパッケージの変更は、それぞれの CHANGELOG を参照する（[plugin-api](packages/plugin-api/CHANGELOG.md)）。

## 0.2.0 - 2026-10-10

最初のリリース。今までの main（0.1.0 を名乗っていた）から更新する場合は、下の「更新の前に」を必ず読むこと。詳しい手順は [バックエンド運用ガイドの 4.2](docs/backend-operations.md#42-認証を導入したバージョンへの更新) にある。

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

2026-10 のセキュリティ監査（`docs/security-audit-report-2026-10-05.md`）の指摘に対応した。

- SMTP の STARTTLS で証明書を検証する（Issue #236、PR #271）
- CSV の書き出しで、`=` `+` `-` `@` などで始まる値を数式として解釈させない（Issue #238、PR #272）
- プラグインのアップロードの一時ディレクトリを、インストールの後と起動時に消す（Issue #239、PR #272）
- プラグインの権限分離（Issue #235）
  - ワーカーとインストーラに渡す環境変数を許可リストにし、`VEA_SECRET_KEY`・`DATABASE_URL`・LLM や SMTP の資格情報を渡さない。資格情報付きのインデックスやプロキシでは wheel だけを入れる。Linux では本体のプロセスを dumpable でなくし（`VEA_PROCESS_NON_DUMPABLE`）、同じユーザーの親プロセスが秘密を持ったまま残っていれば起動時に警告する（PR #273）
  - Docker イメージで `/app` を root の所有にし、プラグインが本体のコードを書き換えられないようにした。何を守り、何を守れないかを [コレクタプラグインの「脅威モデル」](docs/collector-plugins.md#脅威モデル) にまとめた（PR #275）
- SSH の接続先を、名前解決して検証した IP に接続する（DNS rebinding の対策）。許可するポートを `VEA_SSH_ALLOWED_PORTS` で絞れる。外へ接続して確かめる API に rate limit をかけた（Issue #237、PR #276）

### 主な追加

- **ログインとロール**: ローカルのユーザーでのログイン、viewer・operator・admin の 3 つのロール、ユーザー管理の画面と CLI（`vcenter-event-assistant-admin`）、パスワードの変更、ログインの rate limit とロックアウト、監査ログ（ロガー `vcenter_event_assistant.audit`）。[ログインとロール](docs/user-guides/authentication.md)
- **AD / LDAP でのログイン**: 認証ディレクトリの管理画面、グループとロールの対応表、保存前の接続試験と締め出しの防止。[AD / LDAP でのログイン](docs/user-guides/directory-auth.md)
- **コレクタプラグイン**: 画面からのインストール・アンインストール・設定・「変更を反映」、プラグインごとのワーカープロセス、開発キット（`vcenter-event-assistant-plugin-api`、ひな形の生成、テストハーネス）。[プラグイン（利用者向け）](docs/user-guides/plugins.md)、[コレクタプラグインの開発](docs/collector-plugin-authoring.md)
- **リモートログの収集**: 同梱のプラグイン VEA Remote Logs（`vea.remote.logs`）で、ESXi と vCenter のログを SSH で差分収集する。SSH 鍵の生成・ホスト鍵の承認・接続テストを画面から行う。[画面からリモートログ収集を導入する](docs/remote-log-collector.md)
- **メール通知の配送の分離**: アラートの評価と SMTP の配送を分け、送信予定を保存して再起動後も再送する。通知履歴に配送状態と試行回数を表示する

機能の全体は [機能一覧](docs/features_list.md) を参照する。

### 廃止予告

- ダイジェストのレガシーな環境変数 `DIGEST_SCHEDULER_ENABLED`・`DIGEST_CRON` は 0.3.0 で削除する。使っていると起動時に WARNING が出る

### 既知の制約

- プラグインはアプリと同じ OS のユーザーで動く。SQLite の DB ファイル、インストール中の uv の資格情報、同じユーザーで残った親プロセスの環境変数は、プラグインから読める（Issue #274。[脅威モデル](docs/collector-plugins.md#脅威モデル)）
- Samba の AD では `DOMAIN\user` の形でログインできない（Issue #266）
- グループの DN に独自 OID の属性が含まれると、対応表に登録できない（Issue #251）

### 同梱のパッケージ

- `vcenter-event-assistant-plugin-api` 1.5.0（`network.resolve_ssh_address` を追加）
- `vea-remote-log-collector` 0.3.0（接続の直前に名前解決して検証した IP に接続する）

どちらも本体と一緒に `uv sync` と Docker のビルドで入る。PyPI への公開は別に行う。
