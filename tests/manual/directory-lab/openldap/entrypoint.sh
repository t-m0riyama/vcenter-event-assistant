#!/bin/sh
# 初回の起動で TLS・memberOf・ACL を設定し、検証用のユーザーとグループを投入する。
# 2 回目以降（コンテナを作り直していない間）はそのまま起動する。初期状態に戻すには docker compose down。
set -eu

ADMIN_DN=cn=admin,dc=example,dc=org
PASS='Lab-Passw0rd!'   # 検証専用。本番では使わない

mkdir -p /etc/ldap/tls
cp /certs/ca.pem /certs/openldap.pem /certs/openldap.key /etc/ldap/tls/
chown -R openldap:openldap /etc/ldap/tls
chmod 600 /etc/ldap/tls/openldap.key

if [ ! -f /var/lib/ldap/.seeded ]; then
  slapd -h "ldapi:///" -u openldap -g openldap
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    ldapsearch -Q -Y EXTERNAL -H ldapi:/// -b cn=config -s base >/dev/null 2>&1 && break
    sleep 1
  done
  for f in /ldif/config-*.ldif; do
    ldapmodify -Q -Y EXTERNAL -H ldapi:/// -f "$f"
  done
  ldapadd -x -H ldapi:/// -D "$ADMIN_DN" -w "$PASS" -f /ldif/data.ldif
  kill "$(cat /run/slapd/slapd.pid)"
  while [ -f /run/slapd/slapd.pid ]; do sleep 1; done
  touch /var/lib/ldap/.seeded
fi

# -d 256（stats）: 接続・bind・検索をログに出す。フォアグラウンドで動く
exec slapd -d 256 -h "ldap:/// ldaps:/// ldapi:///" -u openldap -g openldap
