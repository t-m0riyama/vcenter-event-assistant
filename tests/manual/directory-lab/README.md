# AD / LDAP の手動確認環境（directory-lab）

AD / LDAP でのログインを、実際のサーバで手動で確かめるための環境。Samba AD DC と OpenLDAP を Docker Compose で立て、検証用のユーザーとグループを投入する。

- 自動テスト（pytest）や CI では動かさない。ldap3 の MOCK では確かめられないこと（AD の入れ子グループの照合、実サーバが返す DN の表記、自己署名の証明書での TLS、資格情報の確認ダイアログの流れなど）を確かめるときに使う
- 使いどころ: ldap3 の更新、`auth/directory/` やディレクトリ管理画面の変更の後
- パスワードなどの値はすべて検証専用。本番では使わない
- arm64 / amd64 のどちらでも動くよう、イメージは Debian bookworm から作る（Samba 4.17、OpenLDAP 2.5）

## 起動と片付け

リポジトリのルートで実行する。

```bash
docker compose -f tests/manual/directory-lab/compose.yml up -d --build
```

- 初回は `certgen` が検証用の CA とサーバ証明書を `certs/` に作る（git の対象外）。Samba と OpenLDAP は初回の起動でドメインの作成とデータの投入を行う（1 分ほどかかる）
- データはコンテナの中にあり、`stop` / `start` では残る。初期状態に戻すには `down` してから `up` し直す（AD の objectGUID などが変わるので、アプリの DB も作り直す）

```bash
docker compose -f tests/manual/directory-lab/compose.yml down
```

アプリは検証用の設定で起動する（開発用の DB とは別の `data/vea.directory-lab.db`、ポート 8765）。

```bash
sh tests/manual/directory-lab/run-app.sh
```

- ローカルの初期 admin は `labadmin` / `Lab-Passw0rd!local`
- 外部への接続はモックにする（`MOCK_MODE=1`。認証には影響しない）
- 短時間に何度もログインするので、ログインの rate limit を 300 回/分に緩めている
- ディレクトリだけの運用を試すときは `VEA_LOCAL_LOGIN_ENABLED=false sh tests/manual/directory-lab/run-app.sh`（このときは初期 admin の環境変数を渡さない。渡すとアプリが起動を止める）
- やり直すときは `data/vea.directory-lab.db` を消す

## 接続先

ポートはループバック（`127.0.0.1` と `::1`）にだけ公開する。

| サーバ | LDAPS | LDAP（StartTLS） | ベース DN |
|---|---|---|---|
| Samba AD（ドメイン `LAB.EXAMPLE`、NetBIOS 名 `LAB`） | `ldaps://localhost:10636` | `ldap://localhost:10389` | `DC=lab,DC=example` |
| OpenLDAP | `ldaps://localhost:11636` | `ldap://localhost:11389` | `dc=example,dc=org` |

- CA 証明書は `tests/manual/directory-lab/certs/ca.pem`。画面の「CA 証明書」に貼る
- サーバ証明書の SAN は `localhost` だけで、`127.0.0.1` はわざと入れていない。`ldaps://127.0.0.1:10636` にすると、ホスト名の検証が失敗する
- Samba AD は暗号化しない接続での simple bind を断る（`transport_security=none` は失敗する）

## ユーザーとグループ

パスワードはすべて `Lab-Passw0rd!`。

### Samba AD（`OU=VEA,DC=lab,DC=example`）

| ユーザー | 所属グループ | 用途 |
|---|---|---|
| `alice` | `VEA-Admins` | admin |
| `bob` | `VEA-Operators` | operator |
| `carol` | `Nested-Team`（`VEA-Viewers` のメンバー） | 入れ子でだけ viewer になる |
| `dave` | なし（primary group の Domain Users だけ） | どのグループにも一致しない |
| `erin` | `VEA Ops, Tokyo`（DN は `CN=VEA Ops\, Tokyo,OU=VEA,DC=lab,DC=example`） | DN のエスケープの確認 |
| `svc-vea` | なし | サービスアカウント（`svc-vea@lab.example` で bind） |

グループの所属は、コンテナの中の `samba-tool` で変えられる。

```bash
docker compose -f tests/manual/directory-lab/compose.yml exec samba samba-tool group addmembers VEA-Admins bob
docker compose -f tests/manual/directory-lab/compose.yml exec samba samba-tool group removemembers VEA-Admins bob
```

### OpenLDAP（`dc=example,dc=org`）

| ユーザー（`uid=…,ou=people`） | 所属グループ（`ou=groups`） | 用途 |
|---|---|---|
| `alice` | `cn=vea-admins`、`cn=vea-posix-admins`（posixGroup の memberUid） | admin |
| `bob` | `cn=vea-operators` | operator |
| `carol` | `cn=vea-viewers` | viewer |
| `dave` | なし | どのグループにも一致しない |
| `erin` | `cn=Ops Team\, Osaka`（memberOf では `\2C` と表記される） | DN のエスケープの確認 |

| サービスアカウント（`uid=…,ou=services`） | 用途 |
|---|---|
| `svc-vea` | 通常のサービスアカウント |
| `svc-noid` | entryUUID を読めない（ACL）。ID 属性が取れないときの確認 |

memberOf は overlay が作る（`group_mode=member_of` で使える）。`group_search` では `member`（値は DN）か `memberUid`（値はユーザー名）を使う。

## アプリに登録する設定の例

| 項目 | Samba AD | OpenLDAP |
|---|---|---|
| 種類 | Active Directory | LDAP |
| 接続先 | `ldaps://localhost:10636` | `ldap://localhost:11389` |
| 接続の暗号化 | LDAPS | StartTLS |
| CA 証明書 | `certs/ca.pem` の中身 | 同じ |
| サービスアカウント | `svc-vea@lab.example` | `uid=svc-vea,ou=services,dc=example,dc=org` |
| ユーザーの検索ベース | `OU=VEA,DC=lab,DC=example` | `ou=people,dc=example,dc=org` |
| UPN サフィックス | `lab.example` | — |
| グループの調べ方 | 入れ子をたどる（`ad_nested`） | `member_of` |
| 対応表 | `CN=VEA-Admins,OU=VEA,DC=lab,DC=example` → admin など | `cn=vea-admins,ou=groups,dc=example,dc=org` → admin など |

## 既知の制約

- Samba（4.17）は `msDS-PrincipalName` を返さないので、`LAB\alice` の形式ではログインできない（ユーザーが見つからない扱いになる）。sAMAccountName と UPN は使える。Windows の AD はこの属性を返す
- ブラウザの組み込みのペインなど、`window.confirm` を自動で閉じる環境では、ディレクトリ管理画面の保存前の確認がキャンセル扱いになる。普通のブラウザで操作する
