# 認証・認可機能の追加（ローカル DB / AD / LDAP）

最終更新: 2026-10-08

## 進捗

全 8 PR に分けて段階的に実装している。各 PR は単独でマージでき、テストが通る状態にする。

| PR | 内容 | 状態 |
|---|---|---|
| 1 | 土台（users / auth_sessions、settings、roles / passwords / tokens / sessions、管理 CLI） | マージ済み [#245](https://github.com/t-m0riyama/vcenter-event-assistant/pull/245) |
| 2 | ローカルログイン、セッション Cookie、CSRF、rate limit とロックアウト、全 route のロール宣言 | マージ済み [#246](https://github.com/t-m0riyama/vcenter-event-assistant/pull/246) |
| 3 | ユーザー管理 API、初期 admin の自動作成、期限切れセッションの掃除、監査ログ | マージ済み [#247](https://github.com/t-m0riyama/vcenter-event-assistant/pull/247) |
| 4 | ログイン画面とロールに応じた UI、認証の既定有効化 | マージ済み [#248](https://github.com/t-m0riyama/vcenter-event-assistant/pull/248) |
| 5 | ユーザー管理画面とパスワード変更 | マージ済み [#249](https://github.com/t-m0riyama/vcenter-event-assistant/pull/249) |
| 6 | AD/LDAP のバックエンド（ldap3、directory テーブル、`auth/directory/*`、realm、ディレクトリ API） | レビュー中 [#250](https://github.com/t-m0riyama/vcenter-event-assistant/pull/250)（Codex レビュー 13 回分と最後の指摘 2 件を反映済み） |
| 7 | ディレクトリ管理画面と、ログイン画面の realm 選択 | 未着手 |
| 8 | 仕上げ: AD/LDAP 設定手順のユーザーガイド、実サーバでの確認、監査レポートへの対応記録 | 未着手 |

### PR6 の最後の指摘 2 件（2026-10-08 に対応）

1. **DN のエスケープ表記の違い**: `cn=Ops\,EMEA` と `cn=Ops\2CEMEA` が一致しなかった。値のエスケープを戻してから決まった形でエスケープし直して比べるようにした
2. **ログイン中のユーザー無効化との競合**: ユーザー行を読んでから更新するまでに無効化されると、ログインが 200 になっていた。更新した後に `is_active` を読み直し、無効ならセーブポイントを巻き戻して拒否するようにした

## Context

もともとアプリには認証・認可がまったくなく、リバースプロキシで守る前提だった（README、監査レポートでも対象外扱い）。プラグイン管理など任意コード実行に近い API も、環境変数による 404 gate しかなかった。アプリ自体にログインとロール制御を入れ、ローカル DB ユーザー・Active Directory・汎用 LDAP を認証先として使えるようにする。

決定事項（ユーザー確認済み）:
- ロールは 3 つで固定: admin ⊃ operator ⊃ viewer
- AD/LDAP の接続設定は **DB に保存し、管理画面から編集・接続試験する**。bind パスワードは既存の `EncryptedString` で暗号化
- AD/LDAP ユーザーのロールは **グループ DN とロールの対応表** で決め、ログインのたびに評価し直す。どれにも一致しなければログインを拒否
- ログイン先（realm）は **ユーザーが選ぶ**。有効な realm が 1 つだけならプルダウンを出さない
- viewer と operator には設定タブを **読み取り専用** で見せる
- operator にも許可するもの: vCenter 接続テスト。アラート履歴の削除は admin だけ
- API トークンは今回作らない（ブラウザの Cookie セッションだけ）

## アーキテクチャ上の決定
- **パスワードのハッシュ**: argon2-cffi。`anyio.to_thread` で実行。ユーザーが存在しないときもダミーハッシュで検証して、応答時間をそろえる
- **LDAP ライブラリ**: ldap3 2.9.1（同期）。`anyio.to_thread` と `CapacityLimiter(10)`（イベントループごと）で呼ぶ。TLS は `CERT_REQUIRED` が既定
- **セッション**:
  - サーバ側にテーブルを持つ。Cookie にはランダムなトークンを入れ、DB には SHA-256 だけを保存
  - Cookie は本番 `__Host-vea_session`。HttpOnly、SameSite=Strict、本番では Secure
  - 無操作 60 分、絶対期限 12 時間
  - ロールは毎リクエストで users 行から読む。ロール変更・無効化・パスワード変更のときは、そのユーザーのセッションを全部失効させる
  - ディレクトリのユーザーのセッションは、そのディレクトリが有効で、今の接続の方針（本番での `none`、禁止中の `tls_verify=false`）で拒否されない間だけ使える（`resolve_session` で確認。条件は `connection.allowed_by_security` で、「使える admin」の数え方と共通）
- **CSRF**: `CsrfMiddleware`。`/api/*` への POST/PUT/PATCH/DELETE で `X-Requested-With: XMLHttpRequest` を必須にし、Origin も照合する（監査 M-14）
- **全体での強制**:
  - `main.py` の `api` router に `Depends(get_current_principal)` を付ける（未ログインは 401）
  - 各 route に `RequireViewer` / `RequireOperator` / `RequireAdmin` を付ける（不足は 403）
  - `/api/auth/*` の公開 route だけ別の router にする
  - **全 route がロールを宣言しているかをテストで強制する**（`tests/test_route_policy.py`）
- **`VEA_AUTH_ENABLED`**: PR4 で既定 true に切り替え済み。本番では false だと起動を拒否する
- **初期 admin**: users が 0 件のときに `VEA_BOOTSTRAP_ADMIN_USERNAME` / `VEA_BOOTSTRAP_ADMIN_PASSWORD` から作る。復旧用に CLI `vcenter-event-assistant-admin` も用意。plugin worker に渡す環境変数からは bootstrap パスワードを除く
- **ブルートフォース対策**: ログインを rate limit の対象にする。ローカルユーザーは失敗回数でロックアウト。失敗時のメッセージは常に同じ文言
- **監査ログ**: DB には保存せず、logger `vcenter_event_assistant.audit` に構造化ログで出す
- **migration**: Alembic を手書きし、`has_table` などで冪等にする（古い DB の fingerprint stamping で再実行され得るため）

## 「使える admin」の数え方（PR6 で確定）

最後の admin を守る判定（ユーザー管理 API、CLI、ディレクトリ API、起動時の bootstrap）は、すべて **実際にログインに使える admin の経路** を数える。

- ローカルの admin: `VEA_LOCAL_LOGIN_ENABLED` が有効なときだけ数える
- ディレクトリ: admin の対応を持つ、有効なディレクトリを 1 つの経路として数える（初回ログイン前でも admin になれるため、users 行ではなく対応表で判断）
- ただし、今の設定で接続を拒否されるディレクトリは数えない（本番での `transport_security=none`、`VEA_DIRECTORY_ALLOW_INSECURE_TLS=false` のときの `tls_verify=false`）
- 無効にした、または admin の対応を外したディレクトリに残る admin のユーザー行は数えない（ログインするとロールが決め直されるため）
- `ensure_not_last_admin(db, user, settings)`、`count_admin_directories(db, options)`、`directory_admin_available(db, settings)` がこの規則を実装する

## データモデル

- **`users`**（PR1）
  - 列: id, realm_key(`local` | `dir:<uuid>`), subject, username, display_name, email, directory_id(nullable), password_hash(nullable), role(CHECK 制約), is_active, failed_login_count, locked_until, password_changed_at, last_login_at, created_at, updated_at
  - `Unique(realm_key, subject)`
  - subject の中身:
    - AD は `guid:<objectGUID>`
    - LDAP は `uuid:<entryUUID>`。なければ `dn:<正規化した DN>`
    - ローカルは小文字化したユーザー名
    - 512 文字を超える subject は `sha256:<hex>` にする（切り詰めると別の DN と衝突するため）
- **`auth_sessions`**（PR1）: id, token_hash(unique), user_id(FK, CASCADE), created_at, last_seen_at, expires_at, client_ip, user_agent
- **`directory_configs`**（PR6、revision `a8b9c0d1e2f3`）
  - 基本: name(unique), kind(`ad`|`ldap`), is_enabled, sort_order
  - 接続: server_uris(JSON), transport_security(`ldaps`|`starttls`|`none`), tls_verify(既定 true), ca_cert_pem, bind_dn, bind_password(EncryptedString), timeout_seconds
  - ユーザー検索: user_search_base, user_search_filter, username_attribute, ad_upn_suffix, display_name_attribute, email_attribute
  - グループ: group_mode(`ad_nested`|`member_of`|`group_search`), group_search_base, group_search_filter, group_member_attribute, group_member_value
  - downgrade では、テーブルを消す前に `dir:` のユーザーとそのセッションを削除する
- **`directory_group_role_mappings`**（PR6）: directory_id(FK, CASCADE), group_dn, group_dn_normalized, role。`Unique(directory_id, group_dn_normalized)`

## AD/LDAP の挙動（PR6 で確定した仕様）

### 接続と TLS
- `server_uris` は `ldap(s)://ホスト名[:ポート]` の形だけを受け付ける（パス・クエリ・資格情報付き（ユーザー名が空でパスワードだけのものも）・範囲外のポートは 422）。ldap3 の `Server` は URI からホスト・ポート・SSL を読み取る
- 複数の URI は順に試す（フェイルオーバー）。StartTLS に失敗したら中止する
- `tls_verify=true` なら `CERT_REQUIRED` で、`ca_cert_pem` があれば `ca_certs_data` に使う。false なら `CERT_NONE`
- `VEA_DIRECTORY_ALLOW_INSECURE_TLS=false` のときは `tls_verify=false` の保存を 422 にし、既存の設定でも接続時にエラーにする
- 本番では `transport_security=none` を保存も接続も拒否する
- 保存時、`tls_verify=false` や `none` のときは監査ログに WARNING を出す
- bind パスワード: 書き込み専用（応答は `has_bind_password` だけ）。`enc:` で始まる値は拒否する。UTF-8 で 1024 バイトまで（暗号化後も 2048 文字の列に収まる）

### ユーザーの検索と認証
- サービスアカウントで bind → ユーザーを検索 → ちょうど 1 件のときだけ本人として bind
- AD のユーザー名:
  - `@` を含む入力は UPN だけで探す
  - そうでなければ sAMAccountName で探す（UPN サフィックスが設定されていれば UPN も）
  - `DOMAIN\user` は sAMAccountName で候補を探し（上限 20 件。1 件多く求めて、上限を超えたら一意でないとして拒否）、各候補の `msDS-PrincipalName` を BASE 検索で読んで、完全に一致するものだけを残す
- 検索結果がサーバ側の件数上限で打ち切られた（sizeLimitExceeded で、指定した件数に届いていない）ときは不完全として扱い、エラーにする
- フィルタに入れる値はすべて `escape_filter_chars` でエスケープする

### グループとロール
- グループ所属の判定: `member_of`（memberOf 属性）、`ad_nested`（対応表のグループごとに `memberOf:1.2.840.113556.1.4.1941:=` で入れ子も含めて調べる）、`group_search`（member / uniqueMember / memberUid で検索）
- ロールは対応表のうち一致したものの中で最も強いもの。どれにも一致しなければログインを拒否する
- グループ DN の正規化（`normalize_dn`）:
  - 属性名は小文字にする。標準の命名属性の OID（`2.5.4.3` など。`OID.` 接頭辞付きも含む）は名前に置き換える。置き換えるのは本当の区切り（エスケープや引用符の外の `,` / `+`）の直後だけ
  - 値の Unicode の正規化（NFKC）・大文字小文字・空白（連続する空白・前後の空白。RFC 4518）は、比較で区別しないと決まっている属性（cn・ou・dc・uid・sn・givenName・mail など、RFC 4519 の標準の属性のうち equality が caseIgnoreMatch のもの）だけならす
  - 複数値 RDN（`+` でつないだ部分）の中は並べ替える。RDN の順序と `+` / `,` の違いは保つ
  - 値のエスケープ（`\,`、`\2C`、UTF-8 のバイト列の `\C3\A9` など）は実際の文字に戻してから、ldap3 の `escape_rdn` で決まった形にエスケープし直す。戻せない値（UTF-8 として不正なバイト列など）を含む DN は解析できない DN として扱う
  - 引用符で囲んだ値と `#` で始まる 16 進表記の値は、ldap3 が解析できないので登録できない
  - 対応表には DN として解析できる値だけを登録できる（解析できない値、正規化後に 1024 文字を超える値は 422）

### ディレクトリの変更とセッション
- ディレクトリを無効にしたとき、対応表を置き換えたとき、認証・ロールに関わる設定（接続先・TLS・bind DN・検索条件・グループの調べ方など）を変えたときは、そのディレクトリのユーザーのセッションをすべて失効させる。名前・表示順・タイムアウト・bind パスワード・表示名やメールの属性だけの変更では失効させない
- 失効させる前に `updated_at` を書き込んで行をロックする
- ログイン側は、LDAP の呼び出しの後にユーザー行を更新し、その後でディレクトリ行を `FOR UPDATE` で読み直す。無効化されていたり `updated_at` が変わっていたりすれば、セーブポイントを巻き戻してログインを拒否する（理由 `directory_disabled` / `directory_changed`）
- ユーザー行は更新した後に `is_active` を読み直し、無効なら同じく巻き戻して拒否する（理由 `inactive`）。読んでから更新するまでの間に無効化されたときに、使えない Cookie を返さないため
- ロックの順序は、管理側（`admin_change_guard` が admin のユーザー行 → ディレクトリ行）とログイン側（ユーザー行 → ディレクトリ行）でそろえる（PostgreSQL のデッドロックを避けるため）
- ディレクトリ名は一意。並行した作成・名前の変更で一意制約に反したときも 422（500 にしない）
- ディレクトリの削除は、無効にしてからだけ許す。配下のユーザーも削除する
- ディレクトリのユーザーは削除できない（422）。消しても次のログインで作り直されるため、無効化で止める

## エンドポイントと最低ロール
P は公開、A はログインしていれば誰でも、V は viewer、O は operator、Ad は admin。

| 範囲 | 最低ロール |
|---|---|
| `GET /health`、`POST /api/auth/login`、`GET /api/auth/realms` | P |
| `GET /api/auth/me`、`POST /api/auth/logout`、`POST /api/auth/me/password`（ローカルユーザーのみ） | A |
| すべての GET（config, events, logs, `logs/export.csv`, metrics, dashboard, digests, alerts の rules/history, ルール類, vcenters, `plugins/collectors`）と `POST /api/incident-timeline`（計算するだけ） | V |
| `PATCH /events/{id}`、`POST /digests/run`、`POST /ingest/run`、chat の 2 本、`POST /incident-timeline/snapshots/manual`、`POST /alerts/states/resolve`、`GET /vcenters/{id}/test` | O |
| vCenter・スコアルール・イベント種別ガイド・アラートルールの作成・更新・削除・取込、`DELETE /alerts/history/{id}`、plugins collectors の PATCH/reload、`plugins/installed` 全部、plugin_setup 全部（router レベル）、`/api/auth/users*`、`/api/auth/directories*` | Ad |

プラグイン系の既存の 404 gate は残し、その上に admin 要件を重ねる。

ディレクトリ API（PR6、すべて admin）:
- `GET /api/auth/directories`、`POST /api/auth/directories`
- `PATCH /api/auth/directories/{id}`（無効化と、ほかに admin の経路がないときの無効化は 409）
- `PUT /api/auth/directories/{id}/mappings`（admin の対応をなくすとき、ほかに経路がなければ 409）
- `DELETE /api/auth/directories/{id}`（無効なときだけ）
- `POST /api/auth/directories/{id}/test`（connect / user_search / user_bind / groups の段階ごとの結果）

## バックエンドの構成
- `src/vcenter_event_assistant/auth/`: `roles.py`、`passwords.py`、`tokens.py`、`sessions.py`、`local_backend.py`、`service.py`（`authenticate(realm, username, password, ip)` が入口）、`users.py`、`bootstrap.py`、`csrf.py`、`audit.py`、`cli.py`
- `auth/directory/`: `connection.py`（Server / Tls の組み立て、`check_security`）、`backend.py`（検索・bind・グループ判定・`authenticate`）、`role_mapping.py`（DN の正規化とロールの決定）、`spec.py`（DB の行から不変の `DirectorySpec` を作る）、`testing.py`（接続試験）、`runner.py`（スレッド実行と `connect_options`）、`errors.py`
- API: `api/auth_deps.py`、`api/routes/auth.py`、`api/routes/auth_users.py`、`api/routes/auth_directories.py`、`api/schemas/auth_directories.py`

## フロントエンド
- PR4・PR5 で実装済み: `frontend/src/auth/`（AuthProvider、useAuth、AuthGate、LoginScreen、UserMenu、ChangePasswordDialog）、`panels/settings/UsersPanel.tsx`
- ユーザー管理画面では、ディレクトリのユーザーにはパスワード再設定と削除のボタンを出さず、ロールは編集できない（対応表で決まるため）
- PR7 で作るもの:
  - 設定のサブタブ「認証ディレクトリ」（admin のみ）。`DirectoriesPanel.tsx`、`DirectoryForm.tsx`、`GroupRoleMappingsEditor.tsx`、`DirectoryTestResult.tsx`
  - `DirectoryForm` に「サーバ証明書を検証する」トグル（既定オン）。オフにするときは確認ダイアログを出し、オフの間はフォームと一覧に警告バッジ（「証明書を検証しません（中間者攻撃に弱い状態です）」）を出す。全体で禁止されているときは操作できないようにし、理由を表示する
  - ログイン画面の realm の選択肢（有効な realm が 2 件以上のときだけ表示）
  - API の 409（最後の admin の経路を失う変更）と 422（入力の検証）を画面に表示する
  - ディレクトリの削除は、無効にしてから確認ダイアログを出して行う
- スタイルは `variables.css` のトークンを使う。UI での制御は見た目のためだけで、権限の最終判断は常にサーバ側で行う

## テスト
- conftest: `VEA_AUTH_ENABLED=1`。`make_client(role)` で user と session を直接作る。`client` は admin
- `tests/test_route_policy.py`: 全 APIRoute のロール宣言を snapshot で確認する
- `tests/test_rbac_matrix.py`: 全 route について 401 / 403 / 通ることを確認する
- `tests/test_auth_directory.py`（PR6）:
  - ldap3 の `MOCK_SYNC` と `FakeDirectory` で `connection.connect` を差し替える
  - AD の in-chain 照合は MOCK が対応していないので、生成するフィルタ文字列を単体テストする
  - 件数上限・`msDS-PrincipalName` のような MOCK で再現しにくい挙動は、`search` だけを持つ接続のスタブで確かめる
  - 競合（認証中の無効化・対応表の置き換え）は `service.run_directory_call` を差し替えて、認証の途中に変更を割り込ませる
- `tests/test_auth_bootstrap.py`: 起動時の admin 判定（ディレクトリの admin 対応、本番で使えない設定、残った admin 行）
- `tests/test_startup_migration.py`: ディレクトリの migration の downgrade
- 修正のたびに、追加したテストが修正前のコードで失敗することを確かめる
- PostgreSQL 固有の挙動（行ロック・デッドロック）は CI の SQLite では再現できない

## 確認方法
- テスト: `uv run pytest -n auto`、`cd frontend && npm test && npm run e2e`、ruff、mypy
  - E2E はサーバが `frontend/dist` を配信するので、UI を変えたら先に `npm run build`
  - このリポジトリは ruff format の既定（88 桁）にそろえていないので、`ruff format` をリポジトリ全体にかけない
- 手動で確認:
  - bootstrap で admin を作ってログインする
  - viewer と operator を作り、タブ表示と 403 を確認する
  - ロールを変更したとき、相手のセッションが即座に失効することを確認する
- CSRF: ヘッダなしの `curl -X POST /api/ingest/run` と、`Origin: https://evil` を付けたリクエストが 403 になること
- 本番設定（`APP_ENV=production`）: auth を無効にしたとき、または使える admin がいないときに起動を拒否すること。Cookie の属性
- AD/LDAP（PR8 で実施）: Samba AD DC（入れ子グループあり）と OpenLDAP をコンテナで立てて確認する
  - 接続試験
  - UPN・sAMAccountName・`DOMAIN\user` のどれでもログインでき、同じユーザー行になること（`msDS-PrincipalName` が実サーバで返ることも確認）
  - グループから外すと次のログインで拒否されること
  - 自己署名証明書の LDAPS / StartTLS で、CA を指定せず `tls_verify=true` なら失敗し、CA を指定するか `tls_verify=false` にすると成功すること。false のとき UI に警告が出ること
  - 実サーバが返す DN の表記（大文字小文字・エスケープ・OID）と、対応表の DN が一致すること

## PR8 で書くこと（ユーザーガイド）
- AD/LDAP の設定手順（入れ子グループ、UPN、`DOMAIN\user`、CA 証明書、primary group が使えないこと）
- 対応表の DN の書き方（大文字小文字・空白・OID の扱い、エスケープの表記）
- 設定を変えるとログイン中のユーザーが失効すること（どの項目で失効するか）
- ディレクトリのユーザーは削除ではなく無効化で止めること
- 「使える admin」の数え方と、409 になる操作
- 監査レポートへの対応記録

## リスク
- **アップグレード直後**: bootstrap の設定がないと起動しない。curl などから API を使っているスクリプトも動かなくなる。リリースノートで周知する
- **ldap3 はほぼメンテされていない**。DN の解析が厳しい（OID の属性や値の中の `=` を拒否する）など癖がある。AD の入れ子グループの照合は実サーバでの手動確認が必須
- **rate limit**: クライアント IP 単位で数えるので、プロキシの後ろでは全員が同じ IP になる。ローカルユーザーは DB のロックアウトで補える
- **ディレクトリの削除**: CASCADE で配下のユーザーも消える。有効な間は削除を禁止し、確認ダイアログも出す
- **Codex のレビュー**: PR6 では指摘が細部の端のケースへ移りつつ続いた。どこで区切るかは利用者が判断する
