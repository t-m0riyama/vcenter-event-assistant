# AD / LDAP でのログイン（認証ディレクトリ）

Active Directory（AD）や汎用の LDAP サーバのアカウントで、vCenter Event Assistant にログインできるようにする手順と、運用上の注意をまとめる。ロール・ローカルユーザー・ユーザー管理の全体は [ログインとロール](authentication.md) を参照する。

- 設定するのは admin。画面は **設定 → 認証ディレクトリ**（API は `/api/auth/directories`）
- 接続設定は DB に保存する。サービスアカウントのパスワードは暗号化して保存し、画面や API の応答には返さない（`VEA_SECRET_KEY` を設定しておく）
- 有効なディレクトリは、ログイン画面の「認証先」に並ぶ（認証先が 1 つだけなら選択欄は出ない）
- ロールはディレクトリのグループで決める。ログインのたびに所属グループを調べ直し、対応表に一致したうちで最も強いロールを使う。どのグループにも一致しなければログインできない

## 1. 準備

設定を始める前に、ディレクトリの管理者と次を決めておく。

| 準備するもの | 内容 |
|---|---|
| 接続先 | サーバの URI（`ldaps://dc1.example.com` など）。複数あれば上から順に試す（フェイルオーバー） |
| 接続の暗号化 | LDAPS（`ldaps://`、既定のポート 636）か StartTLS（`ldap://`、既定のポート 389）。本番（`APP_ENV=production`）では暗号化しない接続は使えない |
| CA 証明書 | サーバ証明書を発行した CA の証明書（PEM）。取得方法は 2 章。社内 CA や自己署名なら必須。公的な CA ならアプリのサーバの証明書ストアで検証できるので空でよい |
| サービスアカウント | ユーザーを検索するためのアカウントとパスワード。ユーザーとグループの検索、ID 属性（下の 5 章）の読み取りができる権限が要る。空にすると匿名で検索する。AD での作り方は 3 章 |
| ユーザーの検索ベース | ログインさせるユーザーがいる範囲（`OU=Staff,DC=example,DC=com` など） |
| グループとロールの対応 | admin・operator・viewer にするグループ。admin のグループは必ず 1 つ用意する |

- サーバ証明書のホスト名（SAN）は、接続先の URI に書くホスト名と一致している必要がある。IP アドレスで接続するなら、証明書にもその IP アドレスが要る
- AD は、暗号化しない接続でのパスワードによる bind を断ることが多い（`strongerAuthRequired`）。AD では LDAPS か StartTLS を使う。新規の AD で LDAPS がまだ無いときの手順は 2 章

## 2. Windows の AD で LDAPS を有効にし、CA 証明書を取得する

アプリに入れるのは、DC のサーバ証明書を発行した CA の公開証明書である。秘密鍵は要らない。形式は PEM（`-----BEGIN CERTIFICATE-----` から `-----END CERTIFICATE-----` まで）で、画面の「CA 証明書」に貼る。公的な CA が発行し、アプリのサーバがすでに信頼している場合は空でよい。

以下の `dc1.example.com` は、接続先 URI に書く DC の FQDN に置き換える。証明書の SAN とこの名前を揃える。DC が複数あるときは、各 DC にサーバ証明書が要る。発行元が DC ごとに違う自己署名なら、PEM を連結してすべて貼る。同じ CA がすべての DC を発行しているなら、その CA の PEM を 1 つ貼る。

StartTLS（389）も、同じサーバ証明書を使う。

### 新規の AD で LDAPS を有効にする

証明書の無い AD では、636 番は待ち受けていても TLS の開始で接続が切れる（`既存の接続はリモート ホストに強制的に切断されました`）。DC 上で、個人ストアにサーバ証明書が無いことを確かめる。

```powershell
Get-NetTCPConnection -LocalPort 636 | Select-Object LocalAddress, State, OwningProcess
Get-ChildItem Cert:\LocalMachine\My |
    Select-Object Subject, DnsNameList, Issuer, NotAfter, HasPrivateKey, EnhancedKeyUsageList
```

636 が Listen でも、`LocalMachine\My` に秘密鍵があり、用途が Server Authentication（`1.3.6.1.5.5.7.3.1`）で、DNS 名が接続先と一致する証明書が無ければ LDAPS は使えない。

社内 CA がまだ無いときは、DC 上で自己署名証明書を作る。`New-SelfSignedCertificate` の既定はサーバ認証用で、Server Authentication が入る。作った証明書は、コンピュータの個人ストアに加え、信頼されたルート証明機関（`LocalMachine\Root`）にも入れる。ルートに入れないと、Schannel が証明書を選ばない。**`NTDS` の再起動中は、この DC でのドメイン認証が一時的に切れる。**

```powershell
$hostname = "dc1.example.com"
$cert = New-SelfSignedCertificate `
    -DnsName $hostname `
    -CertStoreLocation "Cert:\LocalMachine\My" `
    -NotAfter (Get-Date).AddYears(2)
Export-Certificate -Cert $cert -FilePath C:\Windows\Temp\dc-ldaps.cer | Out-Null
Import-Certificate -FilePath C:\Windows\Temp\dc-ldaps.cer -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
Restart-Service NTDS -Force
$b64 = [Convert]::ToBase64String($cert.RawData, "InsertLineBreaks")
"-----BEGIN CERTIFICATE-----"
$b64
"-----END CERTIFICATE-----"
```

自己署名では、この証明書自身が CA である。表示された PEM を「CA 証明書」に貼る。

再起動のあと、PowerShell を開き直して Subject が出ることを確かめる。失敗した接続の `$ssl` は切れているので、作り直さずに `AuthenticateAsClient` だけを再実行しない。

```powershell
$hostname = "dc1.example.com"
$tcp = New-Object System.Net.Sockets.TcpClient($hostname, 636)
$callback = { param($sender, $cert, $chain, $errors) return $true }
$ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false, $callback)
$ssl.AuthenticateAsClient($hostname, $null, [System.Security.Authentication.SslProtocols]::Tls12, $false)
$ssl.RemoteCertificate.Subject
$ssl.Dispose(); $tcp.Dispose()
```

`CN=dc1.example.com` のように Subject が出れば、LDAPS は使える。Windows PowerShell 5.1 は、ホスト名だけの `AuthenticateAsClient` だと古い TLS で交渉して切られることがある。TLS 1.2 を明示する。

社内 CA（AD CS など）があるときは、自己署名の代わりに DC の `certlm.msc` で **個人 → すべてのタスク → 新しい証明書の要求** を開き、「Domain Controller Authentication」または「Kerberos Authentication」を発行する。SAN に接続先の FQDN を含める。発行後に `Restart-Service NTDS -Force` し、次の手順で CA の PEM を取得する。

### CA 証明書を取得する

自己署名で上の手順を実行したときは、その場で表示した PEM を使う。それ以外で LDAPS が既に使えるときは、DC に届く Windows で次を実行する。発行元の CA があれば、その PEM だけが出る（先頭のサーバ証明書は出ない）。中間 CA とルートの両方が出たときは、ブロックを連結したまま貼る。自己署名で発行元が無いときは、サーバ証明書自身の PEM が出るので、それを貼る。

```powershell
$hostname = "dc1.example.com"
$tcp = New-Object System.Net.Sockets.TcpClient($hostname, 636)
$callback = { param($sender, $cert, $chain, $errors) return $true }
$ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false, $callback)
$ssl.AuthenticateAsClient(
    $hostname,
    $null,
    [System.Security.Authentication.SslProtocols]::Tls12,
    $false
)
$leaf = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
$chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
$chain.ChainPolicy.RevocationMode = "NoCheck"
[void]$chain.Build($leaf)
$certs = @($chain.ChainElements | Select-Object -Skip 1 | ForEach-Object { $_.Certificate })
if ($certs.Count -eq 0) { $certs = @($leaf) }
foreach ($cert in $certs) {
    $b64 = [Convert]::ToBase64String($cert.RawData, "InsertLineBreaks")
    "-----BEGIN CERTIFICATE-----"
    $b64
    "-----END CERTIFICATE-----"
}
$ssl.Dispose(); $tcp.Dispose()
```

AD CS の発行元 CA では、次でも PEM にできる。下位 CA が DC の証明書を出しているときは、ルートではなくその下位 CA で実行する。

```cmd
certutil -ca.cert C:\Windows\Temp\ca.cer
certutil -encode C:\Windows\Temp\ca.cer C:\Windows\Temp\ca.pem
```

`ca.pem` の中身を貼る。GUI なら、CA サーバの `certsrv.msc` で CA 名のプロパティを開き、**全般 → 証明書の表示 → 詳細 → ファイルにコピー** で **Base 64 encoded X.509 (.CER)** を選ぶ。

## 3. AD の設定例

| 項目 | 例 | 説明 |
|---|---|---|
| 種類 | Active Directory | |
| サーバ | `ldaps://dc1.example.com`（1 行に 1 つ） | DC を複数書くと、接続できない DC を飛ばして次を使う |
| 暗号化 | LDAPS | StartTLS でもよい |
| CA 証明書 | 2 章で取った PEM | 自己署名なら、その証明書自身 |
| サービスアカウントの DN | `svc-vea@example.com` | UPN でも DN（`CN=svc-vea,OU=Service,DC=example,DC=com`）でもよい |
| 検索ベース | `OU=Staff,DC=example,DC=com` | |
| UPN サフィックス | `example.com` | ユーザー名だけの入力で UPN も探すときに使う（任意） |
| グループの調べ方 | 入れ子のグループも含める（AD） | 下の「入れ子のグループ」を参照 |
| 対応表 | `CN=VEA-Admins,OU=Groups,DC=example,DC=com` → 管理者 など | |

### サービスアカウントを作る

AD は匿名の検索を既定で許可しない。ログインするユーザーとは別に、検索専用のユーザーを 1 つ作る。ドメインの一般ユーザーで足りる。Domain Admins などの管理グループには入れない。

書き込みできるドメインコントローラー、または RSAT の Active Directory モジュールが入った Windows で、そのドメインにユーザーを作成できるアカウントとして実行する。スクリプトは、実行しているコンピューターのドメインに作る。ドキュメントの例 `DC=example,DC=com` のまま実行すると、その名前のドメインが無いサーバは `サーバーがプロセスを実行しようとしません` で拒否する。読み取り専用ドメインコントローラー（RODC）でも同じエラーになる。別のドメインに作るときは、先に `$domain = Get-ADDomain -Identity "other.example.com"` とする。`OU=Service` が直下にあれば、作成は飛ばす。スクリプト内の文字列は ASCII だけにする。Windows PowerShell 5.1 は、引用符の直前に日本語があると閉じ引用符を読み落とすことがあり、`文字列に終端記号 " がありません` になる。

```powershell
$domain = Get-ADDomain
$domainDn = $domain.DistinguishedName
$ouDn = "OU=Service,$domainDn"
$existing = Get-ADOrganizationalUnit -LDAPFilter "(ou=Service)" -SearchBase $domainDn -SearchScope OneLevel -ErrorAction SilentlyContinue
if (-not $existing) {
    New-ADOrganizationalUnit -Name "Service" -Path $domainDn
}
$password = Read-Host -Prompt "Password" -AsSecureString
$params = @{
    Name                 = "svc-vea"
    SamAccountName       = "svc-vea"
    UserPrincipalName    = "svc-vea@$($domain.DNSRoot)"
    Path                 = $ouDn
    AccountPassword      = $password
    Enabled              = $true
    PasswordNeverExpires = $true
    CannotChangePassword = $true
    AccountNotDelegated  = $true
    Description          = "vCenter Event Assistant directory search"
}
New-ADUser @params
Get-ADUser -Identity "svc-vea" | Select-Object UserPrincipalName, DistinguishedName
```

画面には、最後に表示された UserPrincipalName か DistinguishedName を「サービスアカウントの DN」に、入力したパスワードを「サービスアカウントのパスワード」に入れる。ドメインが example.com なら、UPN は `svc-vea@example.com`、DN は `CN=svc-vea,OU=Service,DC=example,DC=com` になる。

GUI なら `dsa.msc` でドメインの直下に `OU=Service` を作り、そこを右クリックして **新規作成 → ユーザー** を開く。ログオン名は `svc-vea`、UPN サフィックスはそのドメインの DNS 名にする。パスワードを設定し、「ユーザーはパスワードを変更できない」「パスワードを無期限にする」を選ぶ。作成後のプロパティの **アカウント** で「アカウントは重要なので委任できない」を選ぶ。

- 検索ベース（例では `OU=Staff`）の外に置く。ロールのグループ（`VEA-Admins` など）には入れない。パスワードを知っていても、対応表のグループに入っていなければ、このアカウントではログインできない
- 既定の ACL では、認証されたユーザーはユーザーとグループを読める。検索ベースの OU からその読み取りを外しているときは、このアカウントにその OU の読み取りを付ける。アプリが読むのは、その OU のユーザーの `sAMAccountName`、`userPrincipalName`、`objectGUID`、`displayName`、`mail` である。グループの調べ方が「ユーザーの memberOf 属性」のときは `memberOf` も読む。`DOMAIN\user` でログインさせるときは `msDS-PrincipalName` も読む。入れ子の判定は、ユーザー自身のエントリへの検索で行う
- パスワードを無期限にできない組織では、期限が切れる前に画面の「サービスアカウントのパスワード」を新しい値へ更新する。切れると、そのディレクトリでのログインがすべて失敗する（10 章）

ログイン画面では、次のどの形で入力しても同じユーザーになる。

- sAMAccountName（`alice`）
- UPN（`alice@example.com`）
- `DOMAIN\user`（`EXAMPLE\alice`）。ドメインまで照合し、別のドメインの同じ名前のアカウントは選ばない。**Samba AD では使えない**（Samba は照合に使う `msDS-PrincipalName` を返さないため。sAMAccountName か UPN を使う。Issue #266）

ユーザーは objectGUID で見分ける。アカウント名を変えたり、別の OU に移したりしても、同じユーザーとして扱われる。

### 入れ子のグループ

「グループの調べ方」で選ぶ。

| 調べ方 | 入れ子のグループ | 使いどころ |
|---|---|---|
| 入れ子のグループも含める（AD） | 含める。`VEA-Viewers` のメンバーのグループのメンバーも `VEA-Viewers` に一致する | AD の既定の選択。対応表のグループごとに AD に問い合わせる |
| ユーザーの memberOf 属性 | 含めない（直接のメンバーだけ） | 入れ子を使わないとき |

**primary group（通常は Domain Users）は対応表に使えない。** AD は primary group を memberOf に含めないので、どちらの調べ方でも一致しない。ロールに使うグループには、ユーザーを通常のメンバーとして入れる。

## 4. OpenLDAP などの設定例

| 項目 | 例 | 説明 |
|---|---|---|
| 種類 | LDAP | |
| サーバ | `ldap://ldap.example.com` | |
| 暗号化 | StartTLS | LDAPS でもよい |
| サービスアカウントの DN | `uid=svc-vea,ou=services,dc=example,dc=com` | |
| 検索ベース | `ou=people,dc=example,dc=com` | |
| 検索フィルタ | 空（既定は `(uid={username})`） | 変えるときは `{username}` を含める。例: `(&(objectClass=inetOrgPerson)(mail={username}))` |
| ユーザー名の属性 | 空（既定は `uid`） | 検索フィルタが空のときの検索に使う属性。グループの検索で memberUid と比べるユーザー名も、この属性から取得する |
| ID 属性 | 空（既定は entryUUID） | 下の 5 章 |

グループの調べ方は、ディレクトリの構成に合わせて選ぶ。

| 構成 | グループの調べ方 | 追加の設定 |
|---|---|---|
| memberOf overlay があり、ユーザーに memberOf 属性が付く | ユーザーの memberOf 属性 | なし |
| groupOfNames（`member`）・groupOfUniqueNames（`uniqueMember`） | グループを検索する | グループの検索ベース、メンバーの属性（`member` / `uniqueMember`）、メンバーの値は「既定（ユーザーの DN）」 |
| posixGroup（`memberUid`） | グループを検索する | グループの検索ベース、メンバーの属性は `memberUid`、メンバーの値は **「ユーザー名（memberUid）」** |

memberUid のグループでメンバーの値を既定（DN）のままにすると、どのグループにも一致しない。

## 5. ID 属性（ユーザーを見分ける属性）

アプリは、ディレクトリのユーザーを ID 属性の値で見分け、その値でユーザー行を作る。AD は objectGUID を使うので設定は要らない。LDAP では「ID 属性」で指定する。

| ディレクトリ | ID 属性 |
|---|---|
| OpenLDAP | entryUUID（既定。空のままでよい） |
| 389 Directory Server | nsUniqueId |
| FreeIPA | ipaUniqueID |
| eDirectory | GUID |

- 値がちょうど 1 つで、変わらない属性を選ぶ。DN は使わない（ユーザーの改名や移動で変わると別のユーザーとして作り直され、アプリでの無効化をすり抜けるため）
- サービスアカウントにその属性の読み取り権限が要る。読めないと値がないものとして扱われ、そのユーザーはログインできない
- **ID 属性は、そのディレクトリのユーザーが 1 人でもログインした後は変えられない。** 変えるには、ディレクトリを無効にして削除し、作り直す（配下のユーザーとグループの対応表も消える）。最初の設定で、次の 6 章の接続試験で ID 属性の値が取れることを確かめる

## 6. 接続試験と保存

フォームの下の「接続試験（保存しません）」で、編集中の値のまま試せる。DB には書かず、ログイン中の利用者にも影響しない。

- ユーザー名だけ入れると、接続・サービスアカウントでの bind・ユーザーの検索と ID 属性の値・グループの判定（どのロールになるか）まで試す。対応表を確かめるだけなら、利用者にパスワードを聞かなくてよい
- パスワードも入れると、本人としての bind（user_bind の段階）も試す。admin になるユーザーで試しておくと、保存の後で管理者としてログインできなくなる危険を減らせる。ただし接続試験は、アプリでそのユーザーを無効にしているかは見ない（ログインと保存前の資格情報の確認では拒否される）。**設定 → ユーザー** でそのユーザーが有効なことも確かめる

結果は段階ごとに出る。

| 段階 | 確かめること |
|---|---|
| connect | サーバに接続し、TLS を確立し、サービスアカウントで bind できる |
| user_search | ユーザーがちょうど 1 人見つかる。成功すると DN と ID 属性の値が出る |
| unique_id | ID 属性の値が取れる（失敗したときだけ出る） |
| user_bind | 入力したパスワードで本人として bind できる（パスワードを入れたときだけ） |
| groups | 対応表のどのグループに一致し、どのロールになるか |

### 保存したときの影響

保存した変更によって、そのディレクトリでログイン中の利用者がログアウトされるかどうかが決まる。ローカルや別のディレクトリの利用者は、どの変更でも影響を受けない。

| 変更した項目 | ログイン中の利用者 | 保存前の確認 |
|---|---|---|
| 名前・表示順・表示名の属性・メールアドレスの属性 | そのまま | なし |
| サービスアカウントのパスワード（消す操作を含む）・タイムアウト | そのまま | あり |
| サーバ・暗号化・証明書の検証・CA 証明書・サービスアカウントの DN・検索ベース・検索フィルタ・ユーザー名の属性・UPN サフィックス・ID 属性・グループの調べ方とその設定・グループとロールの対応 | **全員ログアウトされる** | あり |
| 無効にする | **全員ログアウトされる** | あり |
| 有効にする（無効だったディレクトリ） | いない（無効の間はログインできない） | あり |

「保存前の確認」がある変更は、誤るとこの後のログインがすべて失敗する。画面は、編集中の値での接続試験が成功していなければ、このまま保存するかを確かめる。ログアウトされる変更では、その旨も確かめる。ログアウトされる変更を、自分がログインしているディレクトリで保存したときは、保存の後に自分もログイン画面に戻る。

## 7. グループとロールの対応表の書き方

グループの DN とロール（管理者・オペレーター・閲覧者）を 1 行ずつ登録する。ユーザーが複数のグループに一致したら、最も強いロールになる。

DN は、ディレクトリが返す表記と多少違っていても一致する。

- 属性名の大文字小文字（`CN=` と `cn=`）は区別しない
- `cn`・`ou`・`dc` など、標準で大文字小文字を区別しない属性は、値の大文字小文字・前後の空白・連続する空白も区別しない
- エスケープの書き方の違いは区別しない。たとえば名前にカンマを含むグループは、AD は `CN=Ops\, Tokyo,...`、OpenLDAP の memberOf は `cn=Ops\2C Tokyo,...` と返すが、どちらで登録しても一致する
- 標準の属性の OID（`2.5.4.3=Admins,...` など）は属性名に置き換えて比べる

次の表記は登録できない（保存時にエラーになる）。

- 値を引用符で囲んだ DN（`CN="Admins",...`）
- `#` で始まる 16 進表記の値
- 標準にない独自の OID の属性名（`1.3.6.1.4.1.9999.1=Admins,...`。Issue #251）

DN が分からないときは、ディレクトリの管理ツールでグループの distinguishedName を確かめる。接続試験の groups の段階は、一致したグループを表示する。

## 8. 運用

### ロールの変更が反映される時期

ロールはログインのたびに決め直す。

- グループに追加・削除しても、**ログイン中のセッションは、期限まで元のロールのまま使える**（無操作 60 分、ログインから 12 時間）。次にログインしたときから新しいロールになる
- 直ちにログインできなくしたいときは、**設定 → ユーザー** でそのユーザーの「ログイン解除」を行うか、無効にする
- ログインで決まったロールが前回と違えば、そのユーザーのほかの端末のセッションは失効する
- **設定 → ユーザー** の一覧（と CLI の `list-users`）のロールは、最後にログインしたときのもの

### ユーザーを無効にする

ディレクトリのユーザーは削除できない（消しても、次のログインで作り直されるため）。ログインを拒否するときは **設定 → ユーザー** で無効にする。無効にしたユーザーは、ディレクトリの資格情報が正しくてもログインできない。ディレクトリ側でアカウントを無効にしたり、グループから外したりしてもよい（反映は上の「ロールの変更が反映される時期」のとおり）。

### ディレクトリを無効にする・削除する

- 無効にすると、そのディレクトリのユーザーは全員ログアウトされ、ログイン画面の認証先からも消える
- 削除できるのは、無効にしたディレクトリだけ。配下のユーザーとグループの対応表も削除する（元に戻せない）
- 自分がログインしているディレクトリは、無効にできない。ローカルや別のディレクトリの管理者でログインし直してから操作する

## 9. 管理者ログイン不能の防止

admin としてログインする手段がなくなる操作は、サーバが 409 で断る。

### 「admin としてログインする手段」の数え方

- ローカルログインが有効（`VEA_LOCAL_LOGIN_ENABLED=true`）なら、有効なローカルの admin
- admin のロールに対応づけたグループを持つ、有効なディレクトリ（まだ誰もログインしていなくても数える）
- ただし、今の設定で接続を断られるディレクトリは数えない（本番での暗号化しない接続、`VEA_DIRECTORY_ALLOW_INSECURE_TLS=false` での証明書を検証しない設定）

### 409 になる操作

| 操作 | 理由 |
|---|---|
| ほかに手段がないのに、ディレクトリを無効にする・admin の対応をなくす | admin がいなくなる |
| 自分がログインしているディレクトリを無効にする | 別の経路でログインして操作する |
| 下の確認が要るのに、資格情報を入れない・確かめられない | 新しい設定で admin としてログインできるか分からない |

### 保存前の資格情報の確認

次のどちらかに当たるとき、ログインの成否に関わる変更（6 章の表で「保存前の確認」があるもの）を保存するには、**新しい設定で admin としてログインできるユーザーの資格情報**が要る。

- 操作している admin 自身がそのディレクトリでログインしている。ログアウトされる変更なら自分もログアウトされ、そうでない変更（サービスアカウントのパスワード・タイムアウト）でも、今のセッションが切れた後にログインし直せなくなるおそれがあるため
- ほかに admin としてログインする手段がない

画面では、資格情報を入力するダイアログが出る。サーバは、新しい設定で本番のログインと同じ処理（ユーザーの検索・ID 属性・本人としての bind・グループの判定）を行い、admin になることを確かめてから保存する。確かめられなければ理由が出るので、入れ直す。資格情報は確認にだけ使い、保存しない。アプリで無効にしたユーザーの資格情報では確かめられない。

## 10. 管理者ログイン不能からの復旧

ディレクトリ側の変更（admin のグループからの削除、サービスアカウントのパスワードの期限切れなど）で、admin が誰もログインできなくなったときは、サーバ上の CLI で復旧する。

1. ローカルの admin の状態を確かめる

   ```bash
   uv run vcenter-event-assistant-admin list-users
   ```

2. ローカルの admin のパスワードを再設定する（ロックも解除される）。ローカルの admin がいなければ作る。一覧で `ACTIVE` が `no`（無効）なら、パスワードを再設定しても有効にはならないので、`unlock` で有効にする

   ```bash
   uv run vcenter-event-assistant-admin reset-password admin
   ```

   ```bash
   uv run vcenter-event-assistant-admin create-user rescue-admin --role admin
   ```

   ```bash
   uv run vcenter-event-assistant-admin unlock admin
   ```

3. ディレクトリだけで運用していた（`VEA_LOCAL_LOGIN_ENABLED=false`）なら、`VEA_LOCAL_LOGIN_ENABLED=true` にしてアプリを再起動する
4. ローカルの admin でログインし、**設定 → 認証ディレクトリ** で設定を直す
5. 必要なら `VEA_LOCAL_LOGIN_ENABLED=false` に戻して再起動する

- CLI は、アプリと同じ `DATABASE_URL` と `VEA_SECRET_KEY` で実行する。Docker Compose では `docker compose exec app vcenter-event-assistant-admin ...` のように実行する
- パスワードは対話で入力するか、`--password-stdin` で標準入力から渡す（コマンドライン引数では受け取らない）

## 11. ディレクトリだけで運用する

ローカルログインを無効にし、ディレクトリのアカウントだけで運用するときは、`VEA_LOCAL_LOGIN_ENABLED=false` にする。

- admin のロールに対応づけたグループを持つ、有効なディレクトリが必要（本番では、ないと起動しない）
- **`VEA_BOOTSTRAP_ADMIN_USERNAME` / `VEA_BOOTSTRAP_ADMIN_PASSWORD` は環境から消す。** 残っていると、初期 admin（ローカルユーザー）ではログインできないため、アプリは起動を止める
- 管理者としてログインできなくなったときは 10 章の手順でローカルログインを一時的に有効にする

## 12. うまくいかないとき

接続試験の結果と、サーバのログ（`vcenter_event_assistant.audit` の `login_failure` の `reason`）で原因を絞り込む。ログイン画面には、どの原因でも「ユーザー名またはパスワードが正しくありません。」とだけ出る（存在するユーザー名を推測させないため）。

| 接続試験の表示・ログの reason | 主な原因と対処 |
|---|---|
| connect:「サーバ証明書の発行元（CA）を信頼できません」 | CA 証明書が未設定か違う。2 章の手順で、サーバ証明書を発行した CA の PEM を設定する（`directory_tls_error`） |
| connect:「サーバ証明書のホスト名が接続先と一致しません」 | 接続先の URI のホスト名が証明書の SAN にない。証明書に載っている名前で接続する（`directory_tls_error`） |
| connect:「サーバが暗号化した接続を求めています」 | AD に暗号化しない接続をしている。LDAPS か StartTLS にする（`directory_config_error`） |
| connect:「接続できません」 | ホスト名・ポート・ファイアウォール。LDAPS は 636、StartTLS は 389 が既定（`directory_unavailable`） |
| connect:「サービスアカウントで bind できません」 | サービスアカウントの DN かパスワードが違う、またはアカウントがロック・期限切れ（`directory_unavailable`） |
| user_search:「検索の起点のエントリが見つかりません」 | 検索ベースの誤り（`directory_config_error`） |
| user_search:「ユーザーが見つかりません」 | 検索ベースの外にいる、検索フィルタが合わない、Samba AD で `DOMAIN\user` を使った（`unknown_user`） |
| user_search:「同じ名前のユーザーが複数見つかりました」 | 検索ベースが広すぎるか、検索フィルタで一意にならない（`ambiguous_user`） |
| unique_id:「ID 属性 … の値がありません」 | ID 属性の名前の誤りか、サービスアカウントに読み取り権限がない（`directory_missing_unique_id`） |
| user_bind:「パスワードが正しくありません」 | 入力したパスワードの誤り（`bad_password`） |
| groups:「対応表のどのグループにも属していないため、ログインできません」 | 対応表の DN の誤り、グループの調べ方の誤り（入れ子なのに memberOf、memberUid なのにメンバーの値が DN）、primary group を使っている（`no_matching_group`） |

## 関連する設定

| 変数 | 既定 | 内容 |
|---|---|---|
| `VEA_LOCAL_LOGIN_ENABLED` | `true` | ローカルユーザーでのログインを許可する |
| `VEA_DIRECTORY_ALLOW_INSECURE_TLS` | `true` | `false` にすると、サーバ証明書を検証しない設定を禁止する（保存も接続もできない） |
| `VEA_SECRET_KEY` | なし | サービスアカウントのパスワードの暗号化に使う。本番では必須 |
| `APP_ENV` | `development` | `production` では暗号化しない接続を禁止する |

証明書を検証しない設定は、中間者攻撃でサービスアカウントや利用者のパスワードを盗まれるおそれがある。検証用の環境以外では使わず、自己署名の証明書なら CA 証明書を設定する（作り方と取得方法は 2 章）。証明書を検証しないディレクトリには、一覧とフォームに警告が出て、保存時には監査ログに警告が残る。
