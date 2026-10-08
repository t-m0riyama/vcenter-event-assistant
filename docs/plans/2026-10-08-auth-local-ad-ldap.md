# 認証・認可機能の追加（ローカル DB / AD / LDAP）

最終更新: 2026-10-08

## 進捗

全 8 PR に分けて段階的に実装している。各 PR は単独でマージでき、テストが通る状態にする。

| PR | 内容 | 状態 |
|---|---|---|
| 1 | 土台（users / auth_sessions、settings、roles / passwords / tokens / sessions、管理 CLI） | マージ済み [PR #245](https://github.com/t-m0riyama/vcenter-event-assistant/pull/245) |
| 2 | ローカルログイン、セッション Cookie、CSRF、rate limit とロックアウト、全 route のロール宣言 | マージ済み [PR #246](https://github.com/t-m0riyama/vcenter-event-assistant/pull/246) |
| 3 | ユーザー管理 API、初期 admin の自動作成、期限切れセッションの掃除、監査ログ | マージ済み [PR #247](https://github.com/t-m0riyama/vcenter-event-assistant/pull/247) |
| 4 | ログイン画面とロールに応じた UI、認証の既定有効化 | マージ済み [PR #248](https://github.com/t-m0riyama/vcenter-event-assistant/pull/248) |
| 5 | ユーザー管理画面とパスワード変更 | マージ済み [PR #249](https://github.com/t-m0riyama/vcenter-event-assistant/pull/249) |
| 6 | AD/LDAP のバックエンド（ldap3、directory テーブル、`auth/directory/*`、realm、ディレクトリ API） | マージ済み [PR #250](https://github.com/t-m0riyama/vcenter-event-assistant/pull/250)（Codex レビュー 21 回分を確認し、利用者の判断で区切った。持ち越しは Issue #251〜#255・#258。Issue #253 は [PR #256](https://github.com/t-m0riyama/vcenter-event-assistant/pull/256) で対応済み） |
| 7 | ディレクトリ管理画面と、ログイン画面の realm 選択 | 未着手 |
| 8 | 仕上げ: AD/LDAP 設定手順のユーザーガイド、実サーバでの確認、監査レポートへの対応記録 | 未着手 |

### 次にやること

1. PR7: ディレクトリ管理画面と、ログイン画面の realm 選択（下の「フロントエンド」）
   - [Issue #254](https://github.com/t-m0riyama/vcenter-event-assistant/issues/254)（締め出し対策）と [Issue #258](https://github.com/t-m0riyama/vcenter-event-assistant/issues/258)（その確認の抜け）を、同じ PR で PR7 のマージまでに入れる。PR7 の中でも、PR7 の前の小さな PR でもよい。設計は下の「ディレクトリ API」の予定と、Issue #254 の引き継ぎコメントにまとめてある
2. PR8: ユーザーガイドと、Samba AD / OpenLDAP での実機確認（下の「確認方法」「PR8 で書くこと」）
3. [Issue #252](https://github.com/t-m0riyama/vcenter-event-assistant/issues/252)・[Issue #255](https://github.com/t-m0riyama/vcenter-event-assistant/issues/255) の小さな修正（時期は問わない。リリースの前に入れる）

### PR6 のレビューの経過

- Codex の自動レビューは push のたびに走る。21 回分の指摘を確認し、妥当なものは修正コミットを示して返信した
- 後半は、DN の正規化の細かい端のケース（RFC 4518 の文字列の準備、標準の属性の一覧など）へ指摘が移っていった。2026-10-08 に利用者の判断で区切り、残りは Issue にした
- 後半で入った主な仕様（詳細は各節）:
  - グループ DN の照合を RFC 4518 にそろえた（エスケープの表記・NFKC・空白・大文字小文字）
  - 方針で接続を拒否されるディレクトリは、「使える admin」・発行済みセッション・realm の一覧のすべてで除く
  - ディレクトリのログインでロールが変わったら、ほかのセッションを失効させる
  - ログイン中の無効化・同じ名前の並行作成・検索ベースの不在の扱い
- PR #257（この計画の更新）でも、Codex の指摘は Issue #254 の設計の詰めへ続いた。妥当なものは計画と Issue #254 に追記し、最後の 1 件は利用者の指示で Issue #258 にした

### PR6 からの持ち越し（Issue）

| Issue | 内容 | 対応の時期 |
|---|---|---|
| [Issue #253](https://github.com/t-m0riyama/vcenter-event-assistant/issues/253) | entryUUID のない LDAP では DN を ID（subject）に使うので、DN が変わると別のユーザーとして作り直され、アプリ側の無効化をすり抜ける | 対応済み（[PR #256](https://github.com/t-m0riyama/vcenter-event-assistant/pull/256)。ID 属性を設定できるようにし、値がちょうど 1 つ取れなければ拒否する。DN は ID にしない） |
| [Issue #252](https://github.com/t-m0riyama/vcenter-event-assistant/issues/252) | 鍵（`VEA_SECRET_KEY`）を後から設定しても、起動時の暗号化の移行が `vcenters` しか見ないので、ディレクトリの bind パスワードが平文のまま残る（開発用の `VEA_ALLOW_PLAINTEXT_PASSWORDS` で作った場合のみ） | いつでも（小さな修正） |
| [Issue #254](https://github.com/t-m0riyama/vcenter-event-assistant/issues/254) | admin の経路がそのディレクトリだけ（設定上はほかにあっても、実際に動いているのがそのディレクトリだけの場合を含む）のとき、認証に関わる設定や対応表を誤って変えると、セッションがすべて失効して誰もログインできなくなる（復旧は CLI） | PR7 のマージまでに（保存前の接続試験・確認ダイアログと合わせて設計する。未保存の設定を試す API が要る） |
| [Issue #258](https://github.com/t-m0riyama/vcenter-event-assistant/issues/258) | Issue #254 の保存前の確認（`directory_backend.authenticate`）は LDAP の資格情報と対応表しか見ないので、アプリ側で無効化されたユーザーの資格情報でも通ってしまう | Issue #254 と同じ PR で（確認の条件に最初から含める） |
| [Issue #255](https://github.com/t-m0riyama/vcenter-event-assistant/issues/255) | ロールの昇格と同時のログインで、先行するログインのセッションの失効が漏れる（PostgreSQL のみ。漏れるのは同じ本人がほぼ同時に作ったセッション） | いつでも（`FOR UPDATE` を足す小さな修正。Issue #252 と同じ PR でよい） |
| [Issue #251](https://github.com/t-m0riyama/vcenter-event-assistant/issues/251) | 独自 OID の属性を使うグループ DN（`1.3.6.1.4.1.9999.1=Admins,...`）は ldap3 が解析できず、対応表の登録時に 422 になる | PR8 の実機確認で必要と分かれば |

## Context

もともとアプリには認証・認可がまったくなく、リバースプロキシで守る前提だった（README、監査レポートでも対象外扱い）。プラグイン管理など任意コード実行に近い API も、環境変数による 404 gate しかなかった。アプリ自体にログインとロール制御を入れ、ローカル DB ユーザー・Active Directory・汎用 LDAP を認証先として使えるようにする。

決定事項（ユーザー確認済み）:
- ロールは 3 つで固定: admin ⊃ operator ⊃ viewer
- AD/LDAP の接続設定は **DB に保存し、管理画面から編集・接続試験する**。bind パスワードは既存の `EncryptedString` で暗号化
- AD/LDAP ユーザーのロールは **グループ DN とロールの対応表** で決め、ログインのたびに評価し直す。どれにも一致しなければログインを拒否
- ログイン先（realm）は **ユーザーが選ぶ**。有効な realm が 1 つだけならプルダウンを出さない（今の接続の方針で拒否されるディレクトリは一覧に出さない）
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
    - LDAP は ID 属性（`directory_configs.unique_id_attribute`、未設定なら entryUUID）の値
      - entryUUID は `uuid:<小文字にした値>`（Issue #253 より前の行と同じ形）
      - ほかの属性は、文字列なら `id:<小文字の属性名>=<値>`、バイナリ（eDirectory の GUID など）なら `id:<小文字の属性名>#<16 進>`
    - ID が取れないユーザーはログインを拒否する（`DirectoryMissingUniqueId`、理由 `directory_missing_unique_id`。運用者向けに警告ログが出る）。DN は改名・移動で変わり、変わると別のユーザーとして作り直されてアプリ側の無効化をすり抜けるので、ID にしない（Issue #253）
    - Issue #253 より前に `dn:` で作られた行は移行しない（ログインには使われなくなる）。認証機能は未リリースなので実害はない
    - ローカルは小文字化したユーザー名
    - 512 文字を超える subject は `sha256:<hex>` にする（切り詰めると別の DN と衝突するため）
- **`auth_sessions`**（PR1）: id, token_hash(unique), user_id(FK, CASCADE), created_at, last_seen_at, expires_at, client_ip, user_agent
- **`directory_configs`**（PR6、revision `a8b9c0d1e2f3`。`unique_id_attribute` は Issue #253 で追加、revision `b9c0d1e2f3a4`）
  - `unique_id_attribute` は LDAP のみ（AD で指定すると 422）。属性名か数字の OID
  - そのディレクトリのユーザー行がある間は変更できない（422）。変えると全員の subject が変わり、無効化をすり抜けられるため。未設定と `entryUUID` の明示は同じとみなす
  - ディレクトリのユーザーは個別に削除できないので、変えるにはディレクトリを無効にして削除し、作り直す（ユーザーと対応表も消える）。ユーザーの一括削除の操作は、無効化の情報まで消えてすり抜けの経路になるので用意しない（利用者の判断）
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
- bind パスワード: 書き込み専用（応答は `has_bind_password` だけ）。`enc:` で始まる値は拒否する。UTF-8 で 1024 バイトまで（暗号化後も 2048 文字の列に収まる）。鍵を後から設定したときの移行は未対応（Issue #252）

### ユーザーの検索と認証
- サービスアカウントで bind → ユーザーを検索 → ちょうど 1 件のときだけ本人として bind
- AD のユーザー名:
  - `@` を含む入力は UPN だけで探す
  - そうでなければ sAMAccountName で探す（UPN サフィックスが設定されていれば UPN も）
  - `DOMAIN\user` は sAMAccountName で候補を探し（上限 20 件。1 件多く求めて、上限を超えたら一意でないとして拒否）、各候補の `msDS-PrincipalName` を BASE 検索で読んで、完全に一致するものだけを残す
- 検索の起点がない（結果コード 32 `noSuchObject`）ときは、0 件ではなく設定の誤り（`directory_config_error`、運用者向けの警告を出す）として扱う
- 検索結果がサーバ側の件数上限で打ち切られた（sizeLimitExceeded で、指定した件数に届いていない）ときは不完全として扱い、エラーにする
- フィルタに入れる値はすべて `escape_filter_chars` でエスケープする

### グループとロール
- グループ所属の判定: `member_of`（memberOf 属性）、`ad_nested`（対応表のグループごとに `memberOf:1.2.840.113556.1.4.1941:=` で入れ子も含めて調べる）、`group_search`（member / uniqueMember / memberUid で検索）
- ロールは対応表のうち一致したものの中で最も強いもの。どれにも一致しなければログインを拒否する
- ログインで決まったロールが前回と違えば、そのユーザーのほかのセッションを失効させる（ローカルユーザーのロール変更と同じ）。同じロールなら別の端末のセッションは残す
- グループ DN の正規化（`normalize_dn`）:
  - 属性名は小文字にする。標準の属性の OID（`2.5.4.3` など。`OID.` 接頭辞付きも含む）は名前に置き換える。置き換えるのは本当の区切り（エスケープや引用符の外の `,` / `+`）の直後だけ。未知の OID は解析できない DN になる（Issue #251）
  - 値の Unicode の正規化（NFKC）・大文字小文字・空白（連続する空白・前後の空白。RFC 4518）は、比較で区別しないと決まっている属性（RFC 4519 と RFC 4524 で equality が caseIgnoreMatch / caseIgnoreIA5Match の属性すべて）だけならす
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
- `POST /api/auth/directories/{id}/test`（connect / user_search / user_bind / groups の段階ごとの結果）。保存済みの設定で試す
- 予定（PR7・Issue #254）: 未保存の設定を試す API。新規作成用と、既存のディレクトリに編集中の変更を重ねて試すもの（bind パスワードを送らなければ保存済みのものを使う）。DB には書かず、セッションも失効させない。編集中の対応表で、操作している admin が admin のままになるかも確かめられるとよい
- 予定（PR7・Issue #254）: 試験した設定と対応表を 1 回でまとめて保存する API（1 つのトランザクションで反映し、セッションの失効も 1 回にする）。設定の PATCH と対応表の PUT に分けて送ると、1 回目でこのディレクトリのセッションが失効し、唯一の admin が 2 回目を送れなくなるため
  - 次のどちらかに当たるときは、サーバ側で前提を確かめる。(a) 操作している admin がこのディレクトリのユーザーで、この保存で自分のセッションが失効する。(b) 設定上、ほかに admin の経路がない。「ほかの経路がある」の判定（`count_admin_directories`）は設定と方針しか見ず、そのサーバが落ちている・グループが存在しないなど実際には使えない経路も数えるので、(b) だけでは、唯一動いているディレクトリを壊して締め出されることを防げない。操作しているのがローカルの admin なら、自分のセッションは残るので直せる
  - 確かめる内容: リクエストに含めた資格情報で、新しい設定と対応表のもとで本番のログインと同じ処理（`directory_backend.authenticate`。ユーザーの検索・ID 属性の確認・本人としての bind・グループの判定のすべて）を通し、admin に解決されたときだけ保存する。段階を個別に並べて試すと、ID 属性の確認のような段階が抜けるため、ログインの処理そのものを使う。あわせて、確かめた ID のユーザー行があれば有効であること（またはリクエストしている admin 本人と一致すること）も条件にする（`authenticate` はアプリ側の `is_active` を見ないため。Issue #258）。満たさなければ 409。画面で試験を促すだけでは、試験を省いたり途中まで（今の接続試験はユーザー名やパスワードを省くと途中の段階で終わる）にしたりしても保存できてしまうため
  - 今の `PATCH /api/auth/directories/{id}`（認証に関わる項目）と `PUT /api/auth/directories/{id}/mappings` も、上の (a) か (b) に当たるときは 409 で断り、このまとめて保存する API を使うよう案内する（今は無効化と、admin の対応をすべてなくす変更しか止めていないので、誤った接続先や存在しないグループ DN への変更で確認をすり抜けられる）
  - ディレクトリの無効化（`PATCH` で `is_enabled=false`）は、上の (a)（操作している admin がこのディレクトリのユーザー）なら 409 で断り、別の経路（ローカルや別のディレクトリ）でログインして操作するよう案内する。無効にしたディレクトリはログインに使えないので、新しい設定でのログインの確認では安全を確かめられないため。別の経路で実際にログインして操作していることが、その経路が使える証明になる。削除は無効化の後にしかできないので、これで削除も同じ扱いになる

## バックエンドの構成
- `src/vcenter_event_assistant/auth/`: `roles.py`、`passwords.py`、`tokens.py`、`sessions.py`、`local_backend.py`、`service.py`（`authenticate(realm, username, password, ip)` が入口）、`users.py`、`bootstrap.py`、`csrf.py`、`audit.py`、`cli.py`
- `auth/directory/`: `connection.py`（Server / Tls の組み立て、`check_security`）、`backend.py`（検索・bind・グループ判定・`authenticate`）、`role_mapping.py`（DN の正規化とロールの決定）、`spec.py`（DB の行から不変の `DirectorySpec` を作る）、`testing.py`（接続試験）、`runner.py`（スレッド実行と `connect_options`）、`errors.py`
- API: `api/auth_deps.py`、`api/routes/auth.py`、`api/routes/auth_users.py`、`api/routes/auth_directories.py`、`api/schemas/auth_directories.py`

## フロントエンド
- PR4・PR5 で実装済み: `frontend/src/auth/`（AuthProvider、useAuth、AuthGate、LoginScreen、UserMenu、ChangePasswordDialog）、`panels/settings/UsersPanel.tsx`
- ユーザー管理画面では、ディレクトリのユーザーにはパスワード再設定と削除のボタンを出さず、ロールは編集できない（対応表で決まるため）
- PR7 で作るもの:
  - LDAP のときだけ「ID 属性」の入力欄（空なら entryUUID。例: 389 DS は nsUniqueId、FreeIPA は ipaUniqueID、eDirectory は GUID）。ユーザーがいるディレクトリでは編集できないようにし、理由と「変えるにはディレクトリを無効にして削除し、作り直す（ユーザーと対応表も消える）」ことを出す（API も 422 で断る）
  - 設定のサブタブ「認証ディレクトリ」（admin のみ）。`DirectoriesPanel.tsx`、`DirectoryForm.tsx`、`GroupRoleMappingsEditor.tsx`、`DirectoryTestResult.tsx`
  - `DirectoryForm` に「サーバ証明書を検証する」トグル（既定オン）。オフにするときは確認ダイアログを出し、オフの間はフォームと一覧に警告バッジ（「証明書を検証しません（中間者攻撃に弱い状態です）」）を出す。全体で禁止されているときは操作できないようにし、理由を表示する
  - ログイン画面の realm の選択肢（有効な realm が 2 件以上のときだけ表示）。`/api/auth/realms` は、方針で接続を拒否されるディレクトリを返さない
  - API の 409（最後の admin の経路を失う変更）と 422（入力の検証、同じ名前、解析できない DN など）を画面に表示する
  - 接続試験の結果は段階（connect / user_search / unique_id / user_bind / groups）ごとに出す。検索ベースの誤り（noSuchObject）は設定の誤りとして返る
  - user_search の結果には ID 属性の値が出る。取れなければ unique_id の段階が失敗し、「このユーザーはログインできない」と警告する
  - ディレクトリの削除は、無効にしてから確認ダイアログを出して行う
  - 認証に関わる設定や対応表を保存する前に、編集中の値で接続試験を促し（未保存の設定を試す API を使う）、「このディレクトリでログイン中の利用者はログアウトされる」ことを確認ダイアログで伝える（ローカルや別のディレクトリの利用者は影響を受けない。Issue #254）
  - 上の (a)（自分がこのディレクトリのユーザー）か (b)（ほかに admin の経路がない）に当たるときは、保存時に admin の資格情報の入力を求める（サーバが新しい設定で admin になれることを確かめる。Issue #254）
  - 自分がログインしているディレクトリでは、「無効にする」を操作できないようにし、別の経路でログインして操作するよう理由を出す（API も 409 で断る。Issue #254）
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
  - 「読んでから書くまで」の間の割り込み（ログイン中の無効化、名前の確認後の重複）は、`Session` の `before_flush` イベントで同じ接続に UPDATE を流して再現する。同じセーブポイントの中で流れるので、拒否したときは割り込ませた変更も一緒に巻き戻る点に注意
  - 発行する SQL の回数（セッションの一括失効）は、エンジンの `before_cursor_execute` イベントで数える
- `tests/test_auth_bootstrap.py`: 起動時の admin 判定（ディレクトリの admin 対応、本番で使えない設定、残った admin 行）
- `tests/test_startup_migration.py`: ディレクトリの migration の downgrade
- 修正のたびに、追加したテストが修正前のコードで失敗することを確かめる
- PostgreSQL 固有の挙動（行ロック・デッドロック）は CI の SQLite では再現できない
- フロントのテストで `visibilitychange` などのイベントを送るときは、表示を待った後に `act` で保留中の effect を流してから送る（リスナーを登録する effect がまだ走っておらず、CI でまれにイベントを取りこぼした。`AuthGate.test.tsx` の `flushEffects`）

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
- ユーザーの ID に使う属性の選び方（OpenLDAP は entryUUID、389 DS は nsUniqueId、FreeIPA は ipaUniqueID、eDirectory は GUID）。サービスアカウントにその属性の読み取り権限が要ること。DN は ID にしないこと、ユーザーがいる間は変えられないこと（変えるにはディレクトリを作り直す。最初の設定時に接続試験で ID が取れることを確かめる）
- 「使える admin」の数え方と、409 になる操作
- 監査レポートへの対応記録

## リスク
- **アップグレード直後**: bootstrap の設定がないと起動しない。curl などから API を使っているスクリプトも動かなくなる。リリースノートで周知する
- **ldap3 はほぼメンテされていない**。DN の解析が厳しい（OID の属性や値の中の `=` を拒否する）など癖がある。AD の入れ子グループの照合は実サーバでの手動確認が必須
- **rate limit**: クライアント IP 単位で数えるので、プロキシの後ろでは全員が同じ IP になる。ローカルユーザーは DB のロックアウトで補える
- **ディレクトリの削除**: CASCADE で配下のユーザーも消える。有効な間は削除を禁止し、確認ダイアログも出す
- **Codex のレビュー**: push のたびに走り、PR6 では指摘が細部の端のケースへ移りつつ続いた。どこで区切るかは利用者が判断する（PR6 は 21 回目で区切り、残りを Issue にした）。PR7・PR8 でも同じ進め方にする
