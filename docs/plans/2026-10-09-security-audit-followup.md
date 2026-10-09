# 2026-10 セキュリティ監査の残りの対応

最終更新: 2026-10-09（PR1・PR2・PR3a マージ済み。PR3b を実装し、PR の作成前）

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
| 3a | プラグインの子プロセスに渡す環境変数を許可リストにする | Issue #235 | マージ済み [PR #273](https://github.com/t-m0riyama/vcenter-event-assistant/pull/273)（Codex のレビュー 8 回。指摘 11 件に対応した（うち 1 件は制約としてドキュメントに書いた）。下の「PR3a のレビューの経過」） |
| 3b | Docker イメージで `/app` を root 所有にする、脅威モデルのドキュメント | Issue #235 | 実装済み・PR 作成前（下の「PR3b」。ブランチ `fix/docker-app-root-owned`） |
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
  - `warn_if_parent_keeps_secrets`: 親プロセスが同じ UID で、秘密らしい名前の環境変数（大文字と小文字を区別しない）か、名前の末尾が `PROXY`・`_URL`・`_URI`・`_ENDPOINT`・`_INDEX` で値に資格情報を含む変数を持っていれば WARNING を出す（値は出さない。名前による目安で、すべての秘密は見つけられない）。`uv run` や同じ UID のプロセス管理ツールから起動すると、親が起動時の環境を持ったまま残り、ワーカーが `/proc/<親>/environ` を読めるため。Docker イメージは exec で起動するので影響しない
- ドキュメント: `docs/collector-plugins.md`（「プロセス分離」「動的インストール」）、`docs/backend-operations.md`（設定の一覧、4.1、アップグレードの注意の 4.2 の 7）、`docs/getting-started.md`（`uv run` は開発用）、`.env.example`
- 現在のバージョンの制約（ドキュメントに書いた。利用者の判断）: インストールの間、uv が使う資格情報（インデックスとプロキシ）は uv のコマンドラインと環境変数に載り、既に動いているワーカーが `/proc/<uv の pid>/` から読める。同じ UID では防げないので、資格情報の要らない社内ミラーを勧め、将来、インストーラやワーカーを別の UID に分けることを検討する

### PR3a のレビューの経過

- Codex のレビューは 8 回（`e1d209c`〜`388b1ca`）
  - `e1d209c`: 資格情報付きのインデックスで、アップロードした sdist にも `--no-build` が付いて必ず失敗する（P2）→ `1a58692` でオフラインの経路に
  - `1a58692`: 資格情報付きのプロキシが子プロセスに渡る（P1）→ `aeb2c47` で対応。インストール中に uv の `/proc/<pid>/cmdline`・`environ` を既存のワーカーが読める（P1）→ 同じ UID では防げないので、制約としてドキュメントに書いた
  - `aeb2c47`: スキームのないプロキシ（`user:pass@proxy:8080`）の資格情報を見逃す（P1）→ `6d01825`
  - `6d01825`: ホストの後ろにパスがあると見逃す（P1）→ `2bc79b0` で「`@` があれば資格情報あり」に単純化
  - `2bc79b0`: `uv run` などの親プロセスが秘密を持ったまま残る（P1）→ `20d7a13` で起動時の警告とドキュメント
  - `20d7a13`: 下の 2 件（P2）→ 利用者の判断で両方直した（`0d5ed05`）
  - `0d5ed05`: 資格情報を含む URL の変数（`VEA_PLUGIN_INDEX_URL`・プロキシ・`VCENTER_HTTP_PROXY`）を親の警告で見逃す（P2）→ 名前を決めて持ち、値を `url_has_credentials` で判定する。同じユーザーで動き続けるプロセス管理ツールに exec を勧めたのは誤り（P2。前回書き足した案内）→ 別のユーザーで動かすか秘密を持たせない、に直した。どちらも利用者の判断で直した（`388b1ca`）
  - `388b1ca`: `SEARCH_HTTP_PROXY` を見逃す（P2）。`FIRECRAWL_BASE_URL`・`LLM_*_BASE_URL`・`LANGSMITH_ENDPOINT` も同じく漏れていた → 名前の一覧をやめ、名前の末尾（`PROXY`・`_URL`・`_URI`・`_ENDPOINT`・`_INDEX`）と値の資格情報で判定する。警告は名前による目安で、出ないことは安全の保証にならない、とドキュメントに注記した。利用者の判断で、9 回目の再レビューは頼まずにマージした
- 指摘への対応の繰り返しは、利用者の判断で `20d7a13` で区切った。その後も、レビューのたびに細かい指摘が続いたので、8 回目の対応で区切った
- `20d7a13` の指摘（どちらも P2）と対応
  1. `process_hardening.py:27`: 親プロセスの秘密の名前を探す正規表現が大文字だけを見る。Settings は大文字と小文字を区別しないので、`database_url` などの小文字の名前では警告が出ない。見立て: 妥当。正規表現で大文字と小文字を区別しないようにすれば数行で直る。→ `re.IGNORECASE` を付け、小文字の名前のテストを足した
  2. `process_hardening.py:77`: 対話シェルから `.venv/bin/vcenter-event-assistant` を実行してもシェルは置き換わらない。警告とドキュメントでは `exec .venv/bin/vcenter-event-assistant` と明示すべき。見立て: おおむね妥当（シェルの起動後に `export` した値は `/proc/<pid>/environ` に載らないが、起動時から持つ秘密は載る）。警告の文言と 3 つのドキュメントの例を書き換える。→ 警告と `docs/collector-plugins.md`・`docs/backend-operations.md`・`docs/getting-started.md` の例を `exec .venv/bin/vcenter-event-assistant` にした
- 引き継ぎのメモは PR #273 のコメントにも書いた

## PR3b: Docker イメージと脅威モデル（Issue #235）

### 今の状態（2026-10-09 に調べた）

- `Dockerfile`: `chown -R appuser:appuser /app` の後に `USER appuser` で `uv sync` するので、`.venv` とアプリのコードを `appuser`（ワーカーと同じ UID）が書き換えられる。プラグインが本体のコードに永続的な改変を残せる（監査 M-1 の ②）
- compose の 2 つのテンプレートは、既に `read_only: true`・`cap_drop: ALL`・`no-new-privileges`・tmpfs の `/tmp` を使っている。compose で動かす限り `/app` には今も書けない。効くのは compose を使わない `docker run` のとき
- `docker run` で環境変数を何も渡さないと、DB（既定 `sqlite+aiosqlite:///./data/vea.dev.db`）とプラグインの置き場所（既定 `data/plugins`）が `/app/data` になる。`/app` を root 所有にするだけでは起動できなくなる
- 本体は実行時に `/app` の下へ書かない（一時ファイルは `tempfile`、uv のキャッシュは compose では `/tmp/uv-cache`、それ以外は `HOME`）。インストーラは `uv pip install --target <VEA_PLUGIN_DIR>/...` で、`.venv` に書かない
- `alembic_runner._PROJECT_ROOT` と `main.FRONTEND_DIST` は `__file__` からリポジトリのルートを求めるので、プロジェクトは今の editable のインストールのままにする（`--no-editable` にすると `alembic.ini` と `frontend/dist` を見つけられない）

### 変更

- `Dockerfile`
  - `useradd` と、`/var/log/vea`・`/data` の作成と `chown` はそのまま。`/app` は `chown` しない（root 所有のまま）
  - `uv sync --frozen --no-dev` を root で実行し、その後に `USER appuser` にする。`.venv` も root 所有になる
  - editable のソース（`src/`・`packages/`）はビルド時に `python -m compileall -q` でバイトコードにしておく（実行時に `__pycache__` を書けないので。書けなくても動くが、起動のたびにコンパイルし直す）。site-packages は `UV_COMPILE_BYTECODE=1` で `uv sync` がコンパイルする
  - 既定の置き場所を `/data` に寄せる（利用者の判断）: `ENV DATABASE_URL=sqlite+aiosqlite:////data/vea.db`、`ENV VEA_PLUGIN_DIR=/data/plugins`。compose のテンプレートと同じ値。`.env`・compose・`docker run -e` で上書きできる
  - `docker-entrypoint.sh` は変えない（root で起動したときに `/var/log/vea` を `chown` して `runuser` で `appuser` に落とす）
- compose のテンプレートは変えない（`read_only` などは既にある）。コメントだけ、`/app` は root 所有で読み取り専用であることに合わせる
- `docs/collector-plugins.md` に「脅威モデル」の節を設け、今の「プロセス分離」の後半（渡す環境変数・`prctl`・現在のバージョンの制約・起動方法の注意）と合わせて 1 か所にまとめる
  - プラグイン（とインストール中の sdist のビルドのコード）は本体と同じ OS のユーザーで動く。プロセスの分離はハングやクラッシュを閉じ込めるためのもので、セキュリティの境界ではない
  - 守っているもの: 秘密の環境変数（許可リスト）、本体のプロセスの環境変数とメモリ（`prctl`、Linux）、本体のコードと `.venv`（Docker イメージでは root 所有。compose では rootfs も読み取り専用）
  - 守れないもの: 同じユーザーが読めるファイル（SQLite の DB ファイル `/data/vea.db`、`.env`、`/data/plugins` の他のプラグイン）、インストール中の uv のコマンドラインと環境変数、同じユーザーで残った親プロセスの環境変数。PostgreSQL なら、資格情報を渡さない限り DB には入れない
  - 第三者のプラグインが自分で開く接続（SSH・HTTP）の宛先は本体からは強制できない（PR4 の SSRF の対策は同梱のプラグインだけ）
  - 結論: インストールするプラグインは信頼できるものだけにし、管理機能（`VEA_PLUGIN_MANAGEMENT_ENABLED`）は必要なときだけ有効にする
- `docs/backend-operations.md`: アップグレードの注意（4.2）に、Docker イメージで `/app` が読み取り専用になったこと、compose を使わない `docker run` では DB とプラグインの既定の置き場所が `/data` に変わったこと（今まで `/app/data` に置いていたなら、ボリュームを `/data` にマウントし直すか、`DATABASE_URL`・`VEA_PLUGIN_DIR` で元の場所を指定する）を書く
- `docs/getting-started.md`: Docker の節に、compose を使わず `docker run` する場合は `/data` にボリュームをマウントすることを一言書く（今の記述を見て、必要なら）

### 実装と確認の結果（2026-10-09）

- 上の「変更」のとおりに実装した。`docs/getting-started.md` には Docker の追記をしていない（compose の手順だけで `docker run` の手順はないため。`docker run` の利用者向けの注意は `docs/backend-operations.md` の 4.2 の 8 に書いた）。参照先の節の名前を「プロセス分離」から「脅威モデル」に直した
- `docs/collector-plugins.md` の「脅威モデル」には、SQLite の DB は読み書きできるが、`VEA_SECRET_KEY` を同じユーザーが読めるファイルに置かない限り、暗号化した値は復号できないことも書いた
- 確かめたこと（Docker 29.8、Compose v5.5）
  - `appuser` で `/app`・`/app/.venv/bin`・`site-packages`・`/app/src` に書けず、`/data`・`/var/log/vea`・`/tmp` に書ける。`/app/src` の `__pycache__` はビルド時に作られている
  - 環境変数なしの `docker run`（`read_only` なし）で起動し、DB が `/data/vea.db` にできる
  - compose（sqlite・postgres）で起動・ログイン・`examples/example-event-collector` の wheel のアップロードとインストール・「変更を反映」でコレクタが一覧に出る・アンインストール。ログにエラーなし
  - 変更前のイメージでデータとプラグインを作ったボリュームを、変更後のイメージで引き継げる（ログインでき、プラグインが残り、所有者は `appuser` のまま）
- `tests/test_server_settings.py`（compose のファイルを読むテスト）が通る

### Issue #235 の扱い（利用者の判断）

- この PR のマージで Issue #235 を閉じる（PR の本文に `Closes #235`）。閉じるときのコメントに、PR3a（PR #273）と PR3b で対応したことと、同じユーザーでは防げない残りをまとめる
- 残りは新しい Issue に切り出す: 「プラグインのワーカーとインストーラを別の OS のユーザーで動かす」。本体を root で起動して権限を落とす仕組み・ワーカー用の UID・`/data/plugins` と DB ファイルのパーミッション・SQLite の扱い、を検討の材料として書く。PR3a のレビューで分かった、同じ UID では防げないもの（インストール中の uv の資格情報、起動した親プロセスの環境変数）も書く
- Issue の作成とクローズは、文面を確かめてから行う

### 確認

- `docker build` が通ること
- コンテナの中で `appuser` として `/app`・`/app/.venv`・`site-packages` に書けないこと（`touch` が失敗する、`stat` で所有者が root）。`/data`・`/var/log/vea`・`/tmp` には書けること
- compose（sqlite と postgres のテンプレート）で起動し、ログインできること、マイグレーションが適用されること、ログが `/var/log/vea` に出ること
- `VEA_PLUGIN_MANAGEMENT_ENABLED=true` で、同梱のプラグインの wheel（`uv build packages/remote-log-collector` など）をアップロードしてインストールでき、検出のワーカーが動いてコレクタが一覧に出ること。アンインストールもできること
- `docker run`（`read_only` なし、環境変数なし）で起動し、DB とプラグインが `/data` に作られること
- 既存のボリュームの引き継ぎ: 変更前のイメージで compose を起動してデータを作り、変更後のイメージに差し替えても、DB が読めて、ボリュームの所有者が `appuser` のままであること
- 起動時に `__pycache__` を書こうとする警告やエラーが出ないこと
- `uv run pytest -n auto`・ruff・mypy（Python のコードは変えない見込みだが、`tests/test_server_settings.py` が compose のファイルを読むので）

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
