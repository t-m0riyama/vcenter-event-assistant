# ログインとロール

vCenter Event Assistant はアプリ自体にログインとロールによる権限制御を持つ。既定で有効（`VEA_AUTH_ENABLED=true`）で、ブラウザで開くとまずログイン画面が出る。

## ロール

ロールは 3 つで、上位のロールは下位のロールの操作をすべて行える（admin ⊃ operator ⊃ viewer）。

| ロール | 画面での表示 | できること |
|---|---|---|
| viewer | 閲覧者 | チャット以外のタブの閲覧（チャットタブは operator 以上にだけ表示する）、ログの CSV 出力、タイムラインの生成。設定タブはサーバに保存する項目を閲覧のみで表示する |
| operator | オペレーター | viewer の操作に加え、イベントの運用メモの編集、チャット、手動のデータ取得・ダイジェスト実行、タイムラインのスナップショット保存、アラートの解消、vCenter の接続テスト |
| admin | 管理者 | すべての操作。vCenter・スコアルール・イベント種別ガイド・アラートルールの登録・変更・削除、通知履歴の削除、プラグイン管理、ユーザー管理 |

画面は権限のない操作のボタンを隠すが、最終的な判断は常にサーバが行う（権限がなければ 403 を返す）。
設定タブの「一般」と「チャット」はこのブラウザだけに保存する設定なので、どのロールでも変更できる。

## 初めて起動するとき（初期 admin）

ユーザーが 1 人もいない DB で起動すると、次の環境変数から admin を 1 人作る。

```dotenv
VEA_BOOTSTRAP_ADMIN_USERNAME=admin
VEA_BOOTSTRAP_ADMIN_PASSWORD=十分に長いパスワード（既定は 12 文字以上）
```

- 作るのはユーザーが 0 人のときだけで、2 回目以降の起動では何もしない（パスワードを変えても上書きしない）
- ログインできたら `VEA_BOOTSTRAP_ADMIN_PASSWORD` は環境から削除する（残っていると起動時に警告が出る）
- 本番（`APP_ENV=production`）では、admin がいない状態だと起動を止める。開発環境では警告だけ出す

環境変数の代わりに CLI で作ってもよい（パスワードは対話で入力する）。

```bash
uv run vcenter-event-assistant-admin create-user admin --role admin
```

Docker Compose の場合は `docker compose exec app vcenter-event-assistant-admin create-user admin --role admin` のように実行する。

既存の環境を認証付きのバージョンへ更新する場合の手順は、[バックエンド運用ガイドの 4.2](../backend-operations.md#42-認証を導入したバージョンへの更新) を参照する。

## ログイン・ログアウト・パスワード変更

- ヘッダー右上に利用者名とロールが出る。「ログアウト」でセッションを終了する
- ローカルユーザーは「パスワード変更」から自分のパスワードを変えられる。変更すると、ほかの端末のログインは解除される
- 無操作が 60 分続くか、ログインから 12 時間たつとセッションが切れ、ログイン画面に戻る（`VEA_SESSION_IDLE_TIMEOUT_MINUTES` / `VEA_SESSION_ABSOLUTE_TIMEOUT_HOURS`）。画面の自動更新や通知ドットの定期取得は操作に数えないので、画面を開いたまま放置してもセッションは延びない
- パスワードを 5 回続けて間違えると 15 分ロックされる（`VEA_LOGIN_MAX_FAILED_ATTEMPTS` / `VEA_LOGIN_LOCKOUT_MINUTES`）。接続元 IP ごとのログイン試行も 1 分あたり 10 回までに制限する（`RATE_LIMIT_LOGIN_PER_MINUTE`）

## ユーザー管理

admin は **設定 → ユーザー** でユーザーを管理できる（admin 以外と、認証が無効なサーバでは表示しない）。

- **作成**: ローカルユーザーのユーザー名・表示名・メールアドレス・ロール・初期パスワードを指定する。初期パスワードは本人に安全な方法で伝え、本人にヘッダーの「パスワード変更」で変えてもらう
- **編集**: 表示名・メールアドレス・ロール・有効/無効を変える。ディレクトリ（AD / LDAP）のユーザーのロールはグループの対応表で決まるので、ここでは変えられない
- **パスワード再設定**: ローカルユーザーのパスワードを管理者が設定し直す。ロックも解除される
- **ロック解除**: パスワードの連続失敗でロックされたユーザーを、パスワードを変えずに解除する
- **ログイン解除**: そのユーザーのセッションをすべて失効させる（自分に対して行うと、この画面以外のログインを解除する）
- **削除**: 自分自身は削除できない

入力に問題があれば（パスワードが短い、同じユーザー名がある、最後の admin を降格しようとした等）、画面上部に理由が出る。

CLI でも次の操作ができる（管理画面に入れなくなったときの復旧にも使う）。

| 操作 | コマンド |
|---|---|
| 作成 | `vcenter-event-assistant-admin create-user <ユーザー名> --role viewer` |
| パスワード再設定（ロックも解除） | `vcenter-event-assistant-admin reset-password <ユーザー名>` |
| ロール変更 | `vcenter-event-assistant-admin set-role <ユーザー名> operator` |
| ロック解除・有効化 | `vcenter-event-assistant-admin unlock <ユーザー名>` |
| 一覧 | `vcenter-event-assistant-admin list-users` |

- パスワードはコマンドライン引数では受け取らない。対話入力するか、`--password-stdin` で標準入力の 1 行目から渡す
- ロールの変更・無効化・パスワード再設定をすると、そのユーザーのセッションはすべて失効する
- 最後の有効な admin は降格・無効化・削除できない

## AD / LDAP（ディレクトリ）でのログイン

Active Directory や汎用の LDAP サーバのアカウントでもログインできる。接続設定は DB に保存し、admin が `/api/auth/directories` で登録する（管理画面は今後追加予定）。有効なディレクトリはログイン画面の認証先に並ぶ。

- **ロールはグループで決める**: ディレクトリごとに「グループ DN → ロール」の対応表を登録する。ログインのたびに所属グループを調べ直し、一致したうちで最も強いロールを使う。どのグループにも一致しなければログインできない
- **グループの判定方式**: AD は `ad_nested`（入れ子のグループもたどる）か `member_of`。LDAP は `member_of`（ユーザーの memberOf 属性）か `group_search`（groupOfNames の member、groupOfUniqueNames の uniqueMember、posixGroup の memberUid など、グループ側を検索する）
- **ユーザーの識別**: AD は objectGUID、LDAP は entryUUID（なければ DN）で識別する。AD では sAMAccountName でも UPN（`user@example.com`）でも、`DOMAIN\user` でもログインでき、どれも同じユーザーになる
- **接続の暗号化**: LDAPS か StartTLS を使い、サーバ証明書とホスト名を既定で検証する。社内 CA の証明書は PEM 形式で登録できる。証明書の検証を無効にもできるが、保存時に監査ログへ警告を残す。`VEA_DIRECTORY_ALLOW_INSECURE_TLS=false` にすると全体で禁止できる。本番（`APP_ENV=production`）では暗号化しない接続（`none`）を使えない
- **サービスアカウント**: ユーザーの検索に使う。パスワードは暗号化して保存し、API の応答には返さない
- **接続試験**: `POST /api/auth/directories/{id}/test` で、接続・ユーザー検索・本人としての bind・グループ判定を段階ごとに確かめられる
- **無効化と削除**: 無効にすると、そのディレクトリのユーザーのセッションはすべて失効する。削除できるのは無効にしたディレクトリだけで、配下のユーザーも削除する。ログインできる admin がいなくなる無効化・削除はできない
- ディレクトリ専用で運用する（`VEA_LOCAL_LOGIN_ENABLED=false`）場合は、admin に対応づけたグループを持つ有効なディレクトリが必要（ないと本番では起動しない）

## 認証を無効にする（開発用）

`VEA_AUTH_ENABLED=false` にすると従来どおりログインなしで使え、すべてのリクエストを admin として扱う。起動時に警告が出る。**本番（`APP_ENV=production`）では無効にできず、起動を止める。**

## 関連する設定

| 変数 | 既定 | 内容 |
|---|---|---|
| `VEA_AUTH_ENABLED` | `true` | 認証・認可を有効にする |
| `VEA_BOOTSTRAP_ADMIN_USERNAME` / `VEA_BOOTSTRAP_ADMIN_PASSWORD` | なし | 初期 admin |
| `VEA_PASSWORD_MIN_LENGTH` | `12` | ローカルユーザーのパスワード最小長 |
| `VEA_SESSION_IDLE_TIMEOUT_MINUTES` | `60` | 無操作で失効するまでの分数 |
| `VEA_SESSION_ABSOLUTE_TIMEOUT_HOURS` | `12` | ログインから強制失効までの時間 |
| `VEA_SESSION_COOKIE_SECURE` | 本番のみ `true` | Cookie に Secure 属性を付ける。HTTPS で配信するときは `true` |
| `VEA_LOCAL_LOGIN_ENABLED` | `true` | ローカルユーザーでのログインを許可する |
| `VEA_LOGIN_MAX_FAILED_ATTEMPTS` / `VEA_LOGIN_LOCKOUT_MINUTES` | `5` / `15` | ロックアウト |
| `RATE_LIMIT_LOGIN_PER_MINUTE` | `10` | 接続元 IP ごとのログイン試行の上限 |
| `VEA_DIRECTORY_ALLOW_INSECURE_TLS` | `true` | false にすると、AD / LDAP で証明書を検証しない設定を禁止する |

セッション Cookie は同一オリジン専用（SameSite=Strict）で、変更系の API には `X-Requested-With` ヘッダと Origin の一致を求める（CSRF 対策）。別オリジンのフロントから Cookie 付きで呼ぶ構成には対応しない。
