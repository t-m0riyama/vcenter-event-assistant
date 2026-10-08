# ログインとロール

vCenter Event Assistant はアプリ自体にログインとロールによる権限制御を持つ。既定で有効（`VEA_AUTH_ENABLED=true`）で、ブラウザで開くとまずログイン画面が出る。

## ロール

ロールは 3 つで、上位のロールは下位のロールの操作をすべて行える（admin ⊃ operator ⊃ viewer）。

| ロール | 画面での表示 | できること |
|---|---|---|
| viewer | 閲覧者 | すべてのタブの閲覧、ログの CSV 出力、タイムラインの生成。設定タブはサーバに保存する項目を閲覧のみで表示する |
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
- 無操作が 60 分続くか、ログインから 12 時間たつとセッションが切れ、ログイン画面に戻る（`VEA_SESSION_IDLE_TIMEOUT_MINUTES` / `VEA_SESSION_ABSOLUTE_TIMEOUT_HOURS`）
- パスワードを 5 回続けて間違えると 15 分ロックされる（`VEA_LOGIN_MAX_FAILED_ATTEMPTS` / `VEA_LOGIN_LOCKOUT_MINUTES`）。接続元 IP ごとのログイン試行も 1 分あたり 10 回までに制限する（`RATE_LIMIT_LOGIN_PER_MINUTE`）

## ユーザー管理

admin は `/api/auth/users` でユーザーを管理できる（管理画面は今後追加予定）。CLI でも次の操作ができる。

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

セッション Cookie は同一オリジン専用（SameSite=Strict）で、変更系の API には `X-Requested-With` ヘッダと Origin の一致を求める（CSRF 対策）。別オリジンのフロントから Cookie 付きで呼ぶ構成には対応しない。
