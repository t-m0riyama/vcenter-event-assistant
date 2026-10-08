#!/bin/sh
# 検証用の設定でアプリを起動する（リポジトリのルートで実行される前提で、パスはルートから見たもの）。
# 開発用の DB とは別の SQLite を使い、ポートも分ける。値はすべて検証専用で、本番では使わない。
set -eu
cd "$(dirname "$0")/../../.."

export DATABASE_URL="${LAB_DATABASE_URL:-sqlite+aiosqlite:///./data/vea.directory-lab.db}"
export UVICORN_PORT="${LAB_PORT:-8765}"
export MOCK_MODE=1                      # vCenter などの外部接続をモックにする（認証には影響しない）
export VEA_AUTH_ENABLED=true
export VEA_SECRET_KEY=directory-lab-only-secret-key
# 確認で短時間に何度もログインするので、ログインの rate limit（既定 10 回/分）を緩める
export RATE_LIMIT_LOGIN_PER_MINUTE="${LAB_RATE_LIMIT_LOGIN_PER_MINUTE:-300}"
# ローカルの初期 admin。VEA_LOCAL_LOGIN_ENABLED=false で起動するときは渡さない（渡すとアプリが起動を止める）
if [ "${VEA_LOCAL_LOGIN_ENABLED:-true}" != "false" ]; then
  export VEA_BOOTSTRAP_ADMIN_USERNAME=labadmin
  export VEA_BOOTSTRAP_ADMIN_PASSWORD='Lab-Passw0rd!local'
fi
exec uv run vcenter-event-assistant
