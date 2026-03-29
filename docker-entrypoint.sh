#!/bin/sh
# 名前付きボリュームでマウントされた /var/log/vea が root 所有のとき、appuser が書き込めるようにする。
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p /var/log/vea
  chown -R appuser:appuser /var/log/vea
  exec runuser -u appuser -- "$@"
fi
exec "$@"
