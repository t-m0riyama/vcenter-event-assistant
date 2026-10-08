#!/bin/sh
# 初回の起動でドメインを作り、TLS を設定し、検証用のユーザーとグループを投入する。
# 2 回目以降（コンテナを作り直していない間）はそのまま起動する。初期状態に戻すには docker compose down。
set -eu

REALM=LAB.EXAMPLE
DOMAIN=LAB
BASE=DC=lab,DC=example
PASS='Lab-Passw0rd!'   # 検証専用。本番では使わない

if [ ! -f /var/lib/samba/private/sam.ldb ]; then
  rm -f /etc/samba/smb.conf
  samba-tool domain provision \
    --realm="$REALM" --domain="$DOMAIN" --server-role=dc \
    --dns-backend=NONE --use-rfc2307 \
    --option="server services = -dns" \
    --option="dns update command = /bin/true" \
    --adminpass="$PASS" \
    --option="tls enabled = yes" \
    --option="tls keyfile = /etc/samba/tls/samba.key" \
    --option="tls certfile = /etc/samba/tls/samba.pem" \
    --option="tls cafile = /etc/samba/tls/ca.pem"

  # パスワードの期限切れで検証が止まらないようにする
  samba-tool domain passwordsettings set --max-pwd-age=0 --complexity=off

  samba-tool ou add "OU=VEA" 2>/dev/null || samba-tool ou create "OU=VEA"

  for u in alice:Alice:Admin bob:Bob:Operator carol:Carol:Nested dave:Dave:Nogroup erin:Erin:Tokyo svc-vea:Service:VEA; do
    name=${u%%:*}; rest=${u#*:}; given=${rest%%:*}; sur=${rest#*:}
    samba-tool user create "$name" "$PASS" --userou=OU=VEA \
      --given-name="$given" --surname="$sur" --mail-address="$name@lab.example"
  done

  for g in VEA-Admins VEA-Operators VEA-Viewers Nested-Team; do
    samba-tool group add "$g" --groupou=OU=VEA
  done
  # 名前にカンマを含むグループ（DN のエスケープの確認用）。samba-tool は DN をエスケープしないので、
  # Samba のモジュールを通す SamDB で LDIF を入れる
  python3 - <<'PY'
from samba.auth import system_session
from samba.param import LoadParm
from samba.samdb import SamDB

lp = LoadParm()
lp.load_default()
db = SamDB(url="/var/lib/samba/private/sam.ldb", session_info=system_session(), lp=lp)
with open("/seed.ldif") as f:
    db.add_ldif(f.read())
PY

  samba-tool group addmembers VEA-Admins alice
  samba-tool group addmembers VEA-Operators bob
  samba-tool group addmembers vea-ops-tokyo erin
  samba-tool group addmembers Nested-Team carol
  samba-tool group addmembers VEA-Viewers Nested-Team
fi

# 鍵は 0600 でないと Samba が読まない
mkdir -p /etc/samba/tls
cp /certs/ca.pem /certs/samba.pem /certs/samba.key /etc/samba/tls/
chmod 600 /etc/samba/tls/samba.key

exec samba --foreground --no-process-group --debug-stdout
