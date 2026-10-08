# セキュリティ監査レポート（2026-10-05）

**対象リポジトリ:** vcenter-event-assistant  
**監査日:** 2026-10-05  
**対象リビジョン:** `main` @ `8bdd697`  
**監査範囲:** 前回監査（[`security-audit-report-2026-08-23.md`](security-audit-report-2026-08-23.md)）以降に追加された機能を重点的に確認した — コレクタプラグイン管理（アップロード / インデックスインストール、ワーカー、宣言的セットアップ、SSH 鍵・接続先管理）、リモートログ収集・CSV エクスポート、SMTP 通知 outbox

## 監査方針

- 静的コードレビューと設定ファイルの確認による。
- 前回と同じく、認証をリバースプロキシに委ねる設計そのものは指摘対象にしない。認証の有無にかかわらず成り立つ問題（秘密情報の露出、SSRF、MITM、インジェクション等）を報告する。
- 既存 Issue（前回監査分 #159〜#186、静的 API トークン #94 など）と重複する項目は除外した。
- プラグイン管理系 API は `VEA_PLUGIN_MANAGEMENT_ENABLED=true` のときだけ有効になる（既定は無効）。該当項目ではその旨を前提条件に書いている。

---

## エグゼクティブサマリー

| 深刻度 | 件数 |
|--------|------|
| 高     | 0    |
| 中     | 4    |
| 低     | 3    |

| ID | 深刻度 | 概要 |
|----|--------|------|
| M-1 | 中 | プラグインワーカーの権限が分離されていない（秘密情報の環境変数を全継承し、アプリのコードも書き換えられる） |
| M-2 | 中 | SMTP の STARTTLS でサーバ証明書を検証していない |
| M-3 | 中 | SSH 接続先の SSRF 対策が DNS を解決しないため迂回できる。probe 系にレート制限がない |
| M-4 | 中 | CSV エクスポートで数式インジェクション（CSV injection）への対策がない |
| L-1 | 低 | プラグインのアップロードで作った一時ファイルが削除されない |
| L-2 | 低 | プラグインの宣言的設定に秘密値の扱いがない（平文で保存され、API 応答にもそのまま出る） |
| L-3 | 低 | インデックスからのインストールでハッシュ検証も依存の制限もしていない |

---

## 中（Medium）

### M-1. プラグインワーカーの権限分離不足

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **カテゴリ** | 最小権限 / 秘密情報の保護 / サプライチェーン |
| **該当箇所** | `src/vcenter_event_assistant/plugins/remote.py:96-102`（`CollectorWorker.ensure_started`）, `plugins/remote.py:299-305`（`discover_collectors_at`）, `plugins/installer.py:135-140`（`_run_install`）, `Dockerfile`（`chown -R appuser:appuser /app` → `USER appuser` → `uv sync`） |
| **説明** | プラグインのワーカー、検出用のワーカー、`uv pip install` のいずれも `env=` を指定せずに起動しているため、親プロセスの環境変数をすべて引き継ぐ。その中には `VEA_SECRET_KEY`、`DATABASE_URL`、LLM の API キー、`SMTP_PASSWORD`、Tavily/Firecrawl のキーなどが含まれる。さらに Docker イメージでは `/app`（`.venv` とアプリのコードを含む）が実行ユーザー `appuser` の所有になっており、ワーカーも同じ UID で動く。その結果、悪意のあるプラグインや乗っ取られたプラグインは次のことができる。① DB に接続し、`VEA_SECRET_KEY` を使って vCenter のパスワードや SSH 秘密鍵を復号する。② `/app/.venv/.../vcenter_event_assistant` を書き換え、本体プロセスに永続的な改変を残す。sdist をインストールする場合は、ビルドバックエンド（`setup.py` 等）も同じ環境で実行される。プロセス分離はハングを打ち切る目的では機能しているが、セキュリティ境界としては働いていない。 |
| **前提条件** | `VEA_PLUGIN_MANAGEMENT_ENABLED=true` で悪意あるパッケージがインストールされる、または正規のプラグインやその依存がサプライチェーン経由で侵害される |
| **対処方法** | ① ワーカーとインストーラには許可リスト方式で最小限の環境変数（`PATH` / `HOME` / `LANG` / `TZ` / 対象プラグインの `VEA_COLLECTOR_<ID>_*` など）だけを `env=` で渡す。② Docker イメージで `/app` を root 所有の読み取り専用にし、`appuser` が書き込めるのは `/data` と `/var/log/vea` だけにする（`uv sync` は root で実行してから `USER appuser` に切り替える）。③ 可能であればワーカーを別の UID で動かす、read-only rootfs + tmpfs を使う、seccomp を適用する、などを検討する。④ `docs/collector-plugins.md` に「プラグインはホストと同じ権限で動く」という脅威モデルを明記する。 |

---

### M-2. SMTP STARTTLS でサーバ証明書を検証していない

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **カテゴリ** | 通信の機密性・完全性 |
| **該当箇所** | `src/vcenter_event_assistant/services/alerting/notification/email_channel.py:20-33` |
| **説明** | `server.starttls()` を context なしで呼んでいる。この場合 CPython の `smtplib` は `ssl._create_stdlib_context()` を使い、`CERT_NONE`（証明書もホスト名も検証しない）になる。このため、経路上の攻撃者が偽の SMTP サーバとして振る舞い、`SMTP_USERNAME` / `SMTP_PASSWORD` やアラート本文（ホスト名やイベント内容）を盗み見たり書き換えたりできる。`SMTP_USE_TLS=true`（既定）でも暗号化されるだけで、相手の認証はされていない。 |
| **前提条件** | アプリと SMTP サーバの間の経路上に攻撃者がいる（同じセグメントでの ARP/DNS スプーフィング等） |
| **対処方法** | ① `ssl.create_default_context(cafile=settings.smtp_ca_bundle)` を `starttls(context=...)` に渡す。② 社内 CA 向けに `SMTP_CA_BUNDLE` を、ラボ環境向けに明示的なオプトインの `SMTP_TLS_VERIFY=false`（起動時に WARNING を出す）を追加する。③ 必要なら暗黙 TLS（`SMTP_SSL`、465 番ポート）にも対応する。④ 証明書検証が失敗した場合の単体テストを追加する。 |

---

### M-3. SSH 接続先の SSRF 対策迂回 / probe 系 API にレート制限がない

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **カテゴリ** | SSRF / ネットワーク攻撃 |
| **該当箇所** | `src/vcenter_event_assistant/api/routes/plugin_setup.py:459-489`（`validate_host`）, `plugin_setup.py:566-587`（`probe_host_key`）, `plugin_setup.py:249-282`（`execute_action`）, `plugin_setup.py:610-656`（`list_hosts`）, `main.py:65-73`（`_RATE_LIMITED_POST_PATHS`） |
| **説明** | SSH 接続先のホスト名は `validate_vcenter_host(..., resolve_dns=False)` で検証しており、登録時に DNS を引かない。host-key probe（`asyncssh.get_server_host_key`）やセットアップアクション・収集でワーカーが接続する時点でも、解決後の IP を再検証していない（vCenter 側は `collectors/connection.py` で接続直前に再検証している）。そのため、`127.0.0.1` や `169.254.169.254` に解決されるホスト名（外部のワイルドカード DNS など）を登録すれば、IP リテラルを対象とした拒否ルールを迂回できる。ポートも 1〜65535 を自由に指定できるので、probe API を繰り返し呼べばコンテナ内部や同じホストのサービスをポートスキャンできる（応答時間の差やエラーの有無で判別できる）。これらのエンドポイントと `/api/vcenters/{id}/hosts` はレート制限の対象外である。 |
| **前提条件** | `VEA_PLUGIN_MANAGEMENT_ENABLED=true`、かつ管理 API に到達できる利用者がいる |
| **対処方法** | ① probe と接続の直前に名前解決し、ループバック・リンクローカル・メタデータ・マルチキャスト・予約済み・未指定アドレスを拒否する（RFC1918 は現行どおり許可）。ワーカー側にも同じチェックを入れるか、解決済みの IP を渡す。② 許可ポートを設定できるようにする（既定は 22 のみ、など）。③ `/api/plugins/ssh/connections/*/host-key`、`/api/plugins/collectors/*/draft/actions/*`、`/api/vcenters/*/hosts` をレート制限に加える（パターンマッチに対応させる）。 |

---

### M-4. CSV エクスポートの数式インジェクション（CSV injection）

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **カテゴリ** | インジェクション（クライアント側コード実行 / データ流出） |
| **該当箇所** | `src/vcenter_event_assistant/services/log_export.py:74-97`（`csv_row`）, `frontend/src/metrics/metricCsv.ts:5-10`（`escapeCsvField`）, `frontend/src/events/eventCsv.ts`, `frontend/src/events/eventRowToCsv.ts` |
| **説明** | ログ CSV（バックエンド）とイベント / メトリクス CSV（フロントエンド）は、カンマ・引用符・改行のエスケープはしているが、`=` `+` `-` `@` TAB CR で始まる値を無害化していない。ESXi や vCenter のログメッセージ、イベントメッセージ、`user_name`、`entity_name` などは、外部の攻撃者が内容を差し込める（例：SSH や vSphere Client へのログイン失敗時のユーザー名、VM 名）。運用者がこれらの CSV を Excel や LibreOffice で開くと、`=HYPERLINK(...)` や DDE 式が評価され、データの外部送信やコマンド実行の誘導につながる。 |
| **前提条件** | 攻撃者がログやイベントの文字列に影響を与えられ、運用者が CSV を表計算ソフトで開く |
| **対処方法** | ① OWASP の CSV Injection 対策に従い、先頭が `= + - @ \t \r` の値の先頭に `'` を付ける（数値列は除く）。② バックエンド（`csv_row`）とフロントエンド（`escapeCsvField`）の両方に共通関数として入れる。③ 回帰テストを追加する。 |

---

## 低（Low）

### L-1. プラグインのアップロードで作った一時ファイルが削除されない

| 項目 | 内容 |
|------|------|
| **該当箇所** | `src/vcenter_event_assistant/api/routes/plugins.py:356-371` |
| **説明** | `tempfile.mkdtemp(prefix="vea-plugin-upload-")` に保存したパッケージ（最大 50MB）は、インストールが成功しても失敗しても、`start_install` が例外を出しても削除されない。アップロードを繰り返すと `/tmp` が溜まり続け、ディスクが枯渇する。 |
| **対処** | インストールジョブの `finally` と、`start_install` が失敗したときの経路で `shutil.rmtree(staging_dir, ignore_errors=True)` を実行する。起動時に古い `vea-plugin-upload-*` を掃除する処理も入れる。 |

### L-2. プラグインの宣言的設定に秘密値の扱いがない

| 項目 | 内容 |
|------|------|
| **該当箇所** | `src/vcenter_event_assistant/services/plugin_configuration.py:21-43`（`_KEYWORDS`）, `api/routes/plugin_setup.py:111-112,162-168,171-188`, `db/models.py`（`config_values` が JSON 列） |
| **説明** | 設定スキーマには秘密値を表すキーワード（`writeOnly`、`format: password` 相当）がない。そのため、API トークンやパスワードを必要とするプラグインは `config_values` に平文で持たせるしかない。その値は DB の JSON 列に暗号化されずに保存され、`GET /api/plugins/collectors/{id}/configuration` や draft 系 API の応答にもそのまま返る。`draft/import` では、環境変数や TOML で設定した値まで draft にコピーされ、API から見えるようになる。 |
| **対処** | `x-vea-secret: true` キーワードを追加し、該当フィールドは `EncryptedString` 相当で保存、応答ではマスク（未変更なら送らない、の扱い）、ワーカーに渡すときだけ平文に戻す。 |

### L-3. インデックスからのインストールでハッシュ検証も依存の制限もしていない

| 項目 | 内容 |
|------|------|
| **該当箇所** | `src/vcenter_event_assistant/plugins/installer.py:100-126`, `api/routes/plugins.py:297-329` |
| **説明** | `VEA_PLUGIN_ALLOW_INDEX_INSTALL=true` のとき、`name` または `name==version` だけでインストールでき、ハッシュの検証（`--require-hashes`）もしない。依存パッケージも指定したインデックス（既定は PyPI）から解決される。タイポスクワッティングや dependency confusion、インデックス上のパッケージの乗っ取りに対して無防備である（既定は無効）。 |
| **対処** | `==version` とハッシュの指定を必須にする、インストールできる配布物名を許可リストで絞る、`--no-deps` を選べるようにする、社内ミラーの使用をドキュメントで推奨する。 |

---

## 問題なし（今回確認した範囲）

| 領域 | 評価 |
|------|------|
| **Copilot CLI 連携** | `on_permission_request` で全て拒否、`available_tools` は登録したツール名のみ。 |
| **チャット添付** | 件数・テキスト長・画像サイズに上限があり、base64 も厳格に検証している。 |
| **ログ検索 / エクスポート** | ORM のパラメータ化と LIKE エスケープを再利用している。`ZoneInfo` は正規化されていないキーを拒否する。 |
| **メールヘッダインジェクション** | 件名は `splitlines()` の 1 行目で、`EmailMessage` も CR/LF を拒否する。 |
| **SSH 一時鍵ファイル** | `0700` のディレクトリに `O_EXCL` + `0400` で作成し、リクエストごとに削除している。シンボリックリンクと所有者も確認している。 |
| **SSH 秘密鍵の保存** | `EncryptedString`。`VEA_SECRET_KEY` が未設定なら登録を拒否する。一覧 API は公開鍵だけを返す。 |
| **プラグインのアンインストール / アップロードのファイル名** | 生の入力を正規表現で検証しており、パス要素を拒否している。 |
| **requirement の引数注入** | 名前と固定バージョンだけを許可しており、`-` で始まるものは拒否される。 |

---

## 優先対処ロードマップ

1. **M-2** SMTP の証明書検証（小さな変更で効果が大きい）
2. **M-4** CSV の数式インジェクション対策（バックエンドとフロントエンドの共通化）
3. **M-1** ワーカーの環境変数を許可リスト化し、Docker の `/app` を読み取り専用にする
4. **M-3** SSH 接続先を接続時に名前解決して検証、probe 系をレート制限
5. **L-1〜L-3** プラグイン管理の運用強化


---

## 対応状況（2026-10、認証機能の追加）

このレポートは、前回と同じく「認証はリバースプロキシに任せる」前提で書いた。監査の直後（2026-10）に、アプリ自体にログインとロールによる権限制御を追加したので、その影響を記録する。各項目の問題そのものは認証の有無と関係なく残るので、対処はそれぞれ行う。

- 計画と仕様: [`docs/plans/2026-10-08-auth-local-ad-ldap.md`](plans/2026-10-08-auth-local-ad-ldap.md)
- 利用者向け: [ログインとロール](user-guides/authentication.md)、[AD / LDAP でのログイン](user-guides/directory-auth.md)
- 前回のレポートへの影響（CSRF の M-14 など）は、[`security-audit-report-2026-08-23.md`](security-audit-report-2026-08-23.md) の「対応状況」に書いた

| ID | 状況 | 内容 |
|----|------|------|
| M-1、M-3、L-1〜L-3（プラグイン管理） | 前提が変わった | プラグイン管理の API（インストール・アップロード・宣言的セットアップ・SSH 鍵と接続先の管理）は、従来の `VEA_PLUGIN_MANAGEMENT_ENABLED` による無効化に加えて、admin のロールが必要になった。「管理 API に到達できる利用者」は admin に限られる |
| M-4（CSV エクスポート） | 前提が変わった | ログの CSV 出力は viewer 以上のログインが必要になった。数式インジェクションの問題そのものは残る |
| M-2（SMTP） | 変わらない | 認証機能とは関係しない |

認証機能では、このレポートの M-2 と同じ種類の問題（TLS の相手を検証しない）を避けるため、AD / LDAP の接続は既定でサーバ証明書とホスト名を検証する。本番では暗号化しない接続を使えず、`VEA_DIRECTORY_ALLOW_INSECURE_TLS=false` で証明書を検証しない設定も禁止できる。

---

*本レポートはコードベースの静的解析に基づく。動的なペネトレーションテストや、本番環境固有のネットワーク構成は対象外。*
