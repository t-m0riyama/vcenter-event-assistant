#!/bin/sh
# 検証用の CA と、Samba AD・OpenLDAP のサーバ証明書を作る（既にあれば何もしない）。
# ホスト上のアプリは ldaps://localhost:<port> で接続するので、SAN に localhost を入れる。
# 127.0.0.1 はわざと入れない（ldaps://127.0.0.1:<port> でホスト名の検証が失敗することを確かめるため）。
set -eu
OUT=/certs
cd "$OUT"
if [ -f ca.pem ] && [ -f samba.pem ] && [ -f openldap.pem ]; then
  echo "certs: already exist"
  exit 0
fi

openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
  -subj "/CN=VEA Directory Lab CA" \
  -keyout ca.key -out ca.pem \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

issue() {
  name=$1
  sans=$2
  openssl req -newkey rsa:2048 -nodes -subj "/CN=$name" \
    -keyout "$name.key" -out "$name.csr"
  printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature,keyEncipherment\n' "$sans" > "$name.ext"
  openssl x509 -req -in "$name.csr" -CA ca.pem -CAkey ca.key -CAcreateserial \
    -days 825 -sha256 -extfile "$name.ext" -out "$name.pem"
  rm -f "$name.csr" "$name.ext"
}

issue samba "DNS:localhost,DNS:dc1.lab.example,DNS:samba"
issue openldap "DNS:localhost,DNS:ldap.lab.example,DNS:openldap"

chmod 644 ./*.pem ./*.key
echo "certs: generated"
