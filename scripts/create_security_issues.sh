#!/usr/bin/env bash
# Create GitHub issues from security audit report (2026-08-23).
set -euo pipefail
cd "$(dirname "$0")/.."

REPORT="docs/security-audit-report-2026-08-23.md"
LABEL="bug"

create_issue() {
  local id="$1"
  local severity="$2"
  local title="$3"
  local body="$4"

  echo "Creating ${id}: ${title} ..."
  gh issue create \
    --title "[Security/${id}] ${title}" \
    --label "${LABEL}" \
    --body "${body}"
}

create_issue "H-1" "高" "SSRF — vCenter ホスト設定経由の任意宛先接続" "$(cat <<'EOF'
## 概要

vCenter 作成・更新 API で `host` に任意文字列を設定でき、サーバーから任意宛先への TCP 接続（SSRF）が可能。

## 深刻度

**高** — SSRF / ネットワーク攻撃

## 該当箇所

- `src/vcenter_event_assistant/api/schemas/vcenters.py:24`
- `src/vcenter_event_assistant/api/routes/vcenters.py:97-128`
- `src/vcenter_event_assistant/collectors/connection.py:53-77`

## 問題の説明

vCenter 作成・更新 API で `host` に任意文字列（最大 512 文字）を設定可能。プライベート IP、ループバック、クラウドメタデータ（`169.254.169.254`）等のブロックがない。接続テスト（`GET /api/vcenters/{id}/test`）および手動/定期インジェストがサーバーから当該ホストへ TCP 接続する。`http` / `https` 両方が許可される。

## 前提条件

API に到達可能な攻撃者（リバースプロキシ内側の悪意ある利用者、誤設定による公開等）

## 対処方法

1. `host` を FQDN パターンまたは許可サフィックス（`VCENTER_ALLOWED_HOST_SUFFIXES`）で検証
2. プライベート IP・リンクローカル・メタデータ IP を拒否
3. 本番では egress ファイアウォールで vCenter 向け以外の送信を制限
4. 接続テストを管理者限定エンドポイントに分離

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（H-1）
EOF
)"

create_issue "H-2" "高" "vCenter パスワードの平文 DB 保存（VEA_SECRET_KEY 未設定時）" "$(cat <<'EOF'
## 概要

`VEA_SECRET_KEY` 未設定時、vCenter パスワードが DB に平文で保存される。

## 深刻度

**高** — 機密情報の保護

## 該当箇所

- `src/vcenter_event_assistant/db/encrypted_string.py:73-81`
- `src/vcenter_event_assistant/settings.py:108-113`
- `.env.example:18-22`
- `docker-compose.postgres.yml:24-25`

## 問題の説明

`VEA_SECRET_KEY` が未設定の場合、vCenter パスワードは DB に平文で保存・読み取りされる。起動時 WARNING のみで処理は継続。Compose テンプレートでも鍵設定がコメントアウトされており、本番で暗号化なし運用になりやすい。

## 前提条件

DB バックアップ、ボリューム、SQL ダンプ等への不正アクセス

## 対処方法

1. 本番起動時に `VEA_SECRET_KEY` 未設定なら **起動失敗**（`APP_ENV=production` 等で分岐）
2. Compose / `.env.example` で鍵設定を必須化し、生成手順を明記
3. 鍵未設定時は vCenter 作成・更新 API を拒否
4. DB ボリュームの暗号化（at-rest encryption）をインフラ側で適用

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（H-2）
EOF
)"

create_issue "H-3" "高" "vCenter TLS 証明書検証がデフォルト OFF" "$(cat <<'EOF'
## 概要

新規 vCenter 登録の TLS 証明書検証がデフォルトで無効（MITM リスク）。

## 深刻度

**高** — 通信の機密性・完全性

## 該当箇所

- `src/vcenter_event_assistant/api/schemas/vcenters.py:29`
- `src/vcenter_event_assistant/db/models.py:23`
- `src/vcenter_event_assistant/collectors/connection.py:47-49`
- `frontend/src/panels/settings/VCentersPanel.tsx:30,45,75`

## 問題の説明

新規 vCenter 登録のデフォルトが `verify_ssl=False`。`ssl.CERT_NONE` となり MITM により vCenter 認証情報やイベントデータが窃取される可能性がある。フロントエンド UI も同様にデフォルト OFF。

## 前提条件

同一ネットワーク上の攻撃者、または侵害された中間装置

## 対処方法

1. バックエンド・フロントエンドとも **デフォルト `verify_ssl=true`** に変更
2. 検証スキップは明示的オプトイン（「ラボ/開発のみ」警告付き）
3. プライベート CA 利用時は `VCENTER_CA_BUNDLE` の設定手順をドキュメント化

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（H-3）
EOF
)"

create_issue "H-4" "高" "弱いデフォルト DB パスワード" "$(cat <<'EOF'
## 概要

Docker Compose およびアプリ設定に推測可能な DB パスワードのデフォルト値がある。

## 深刻度

**高** — 認証情報 / 設定ミス

## 該当箇所

- `docker-compose.postgres.yml:6,23`
- `src/vcenter_event_assistant/settings.py:32-33`
- `.env.example:6,26`

## 問題の説明

Docker Compose は `POSTGRES_PASSWORD` 未設定時に `vea` を使用。アプリ設定のフォールバックは `postgres:postgres@localhost`。コピペによる本番デプロイで推測可能な認証情報が残る。

## 前提条件

DB ポートへの到達（Compose では Postgres はホスト非公開だが、同一 Docker ネットワークからは到達可能）

## 対処方法

1. Compose で `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD を設定してください}` のように **フォールバックを削除**
2. `settings.py` からハードコード認証情報を除去し、未設定時は起動失敗
3. `.env.example` の `changeme` / `postgres:postgres` をプレースホルダーに置換

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（H-4）
EOF
)"

create_issue "H-5" "高" "チャットプレビュー API による運用データの情報漏洩" "$(cat <<'EOF'
## 概要

`POST /api/chat/preview` が LLM 呼び出しなしで運用データを返す。

## 深刻度

**高** — 情報漏洩

## 該当箇所

- `src/vcenter_event_assistant/api/routes/chat.py:94-117`

## 問題の説明

`POST /api/chat/preview` は LLM 呼び出し不要で、集約イベント、ホスト名、メトリクス、会話履歴を含む `context_block` を返す。`LLM_ANONYMIZATION_ENABLED=false`（開発向け）では実名が含まれる。LLM 設定チェックもない。

## 前提条件

API に到達可能な任意の呼び出し元

## 対処方法

1. 本番では `PREVIEW_API_ENABLED=false`（デフォルト OFF）で無効化
2. 開発環境限定フラグで保護
3. 匿名化を preview でも強制
4. ネットワーク ACL と併用

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（H-5）
EOF
)"

create_issue "M-1" "中" "レート制限の欠如（DoS / リソース枯渇）" "$(cat <<'EOF'
## 概要

高コスト API にアプリケーションレベルのレート制限がない。

## 深刻度

**中** — DoS / リソース枯渇

## 該当箇所

- `src/vcenter_event_assistant/main.py`
- `src/vcenter_event_assistant/api/routes/chat.py`
- `src/vcenter_event_assistant/api/routes/ingest.py`
- `src/vcenter_event_assistant/api/routes/digests.py`

## 問題の説明

LLM チャット、手動インジェスト、ダイジェスト生成、重い DB 集約 API にアプリケーションレベルのレート制限・同時実行数上限がない。

## 対処方法

1. slowapi 等のミドルウェアを導入
2. リバースプロキシでの rate limit
3. LLM/インジェストのグローバル同時実行キャップ
4. `429 Too Many Requests` 応答

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-1）
EOF
)"

create_issue "M-2" "中" "アラート履歴 API のページネーション未制限" "$(cat <<'EOF'
## 概要

アラート履歴 API の `limit` / `offset` に上下限がない。

## 深刻度

**中** — DoS / メモリ枯渇

## 該当箇所

- `src/vcenter_event_assistant/api/routes/alerts.py:175-191`

## 問題の説明

`limit` / `offset` に上下限がなく、巨大な `limit` でメモリ枯渇を誘発可能。他ルート（例: `digests.py:45-46`）は `Query(ge=1, le=200)` を使用。

## 対処方法

`limit: Annotated[int, Query(ge=1, le=200)] = 50` 等を適用。

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-2）
EOF
)"

create_issue "M-3" "中" "チャット系 API の時間範囲上限なし（DoS）" "$(cat <<'EOF'
## 概要

チャット系 API に時間範囲の最大期間制限がない。

## 深刻度

**中** — DoS / DB 負荷

## 該当箇所

- `src/vcenter_event_assistant/api/schemas/chat.py:18-25`
- `src/vcenter_event_assistant/services/chat/chat_context_payloads.py:55-69`

## 問題の説明

`from < to` の検証のみ。最大期間の制限がなく、数年分の範囲指定で大規模 DB スキャンが可能。`/api/events/rate-series` には `EVENT_RATE_MAX_BUCKETS` ガードがあるが、チャット系には同等の制限がない。

## 対処方法

最大期間（例: 30〜90 日）を設定し、超過時は `422` を返す。

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-3）
EOF
)"

create_issue "M-4" "中" "インポート API による全件削除" "$(cat <<'EOF'
## 概要

JSON インポート API で空リスト + 削除フラグにより全件削除が可能。

## 深刻度

**中** — データ整合性

## 該当箇所

- `src/vcenter_event_assistant/api/routes/alerts.py:136-141`
- `src/vcenter_event_assistant/api/routes/event_type_guides.py:88-93`
- `src/vcenter_event_assistant/api/routes/event_score_rules.py:80-85`

## 問題の説明

`delete_*_not_in_import=true` かつ空のインポートリストで `DELETE` が WHERE 句なしの全件削除になる。

## 対処方法

1. 空リスト + 削除フラグの組み合わせを拒否
2. 別途「purge」エンドポイント + 確認トークンを要求

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-4）
EOF
)"

create_issue "M-5" "中" "HTTP セキュリティヘッダー / CSP 未設定" "$(cat <<'EOF'
## 概要

SPA および API レスポンスにセキュリティヘッダーが設定されていない。

## 深刻度

**中** — 防御の多層化

## 該当箇所

- `src/vcenter_event_assistant/main.py:95-105`
- `frontend/index.html`

## 問題の説明

API には `Cache-Control: no-store` のみ。CSP、`X-Frame-Options`、`X-Content-Type-Options`、HSTS がない。XSS 発生時の防御層が薄い。

## 対処方法

1. ミドルウェアまたはリバースプロキシでヘッダー付与
2. CSP は report-only から段階的導入

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-5）
EOF
)"

create_issue "M-6" "中" "OpenAPI ドキュメントが本番でも公開" "$(cat <<'EOF'
## 概要

FastAPI の Swagger / ReDoc / OpenAPI JSON が常時公開されている。

## 深刻度

**中** — 攻撃面の列挙

## 該当箇所

- `src/vcenter_event_assistant/main.py:84`

## 問題の説明

`/docs`, `/redoc`, `/openapi.json` が常時有効。攻撃面の列挙が容易。

## 対処方法

1. 本番では `docs_url=None, redoc_url=None, openapi_url=None`
2. または内部ネットワーク限定

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-6）
EOF
)"

create_issue "M-7" "中" "CORS 設定が過剰に寛容" "$(cat <<'EOF'
## 概要

CORS が credentials + 全メソッド + 全ヘッダーを許可している。

## 深刻度

**中** — 設定ミスリスク

## 該当箇所

- `src/vcenter_event_assistant/main.py:86-93`
- `src/vcenter_event_assistant/settings.py:105-107`

## 問題の説明

`allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`。`CORS_ORIGINS` の誤設定時に credentialed クロスオリジンリクエストを許容しうる。

## 対処方法

1. 必要なメソッド・ヘッダーのみ許可
2. Cookie 未使用なら `allow_credentials=False`
3. 本番 `CORS_ORIGINS` を明示設定

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-7）
EOF
)"

create_issue "M-8" "中" "全インターフェースへのバインド（0.0.0.0）" "$(cat <<'EOF'
## 概要

Uvicorn が全ネットワークインターフェースで待受する。

## 深刻度

**中** — ネットワーク露出

## 該当箇所

- `src/vcenter_event_assistant/__init__.py:15`
- `docker-compose.postgres.yml:18-19`

## 問題の説明

Uvicorn が `0.0.0.0:8000` で待受。Compose は `8000:8000` でホスト全 IF に公開。

## 対処方法

1. リバースプロキシ同梱時は `127.0.0.1:8000:8000`
2. `UVICORN_HOST` 環境変数で制御可能にする

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-8）
EOF
)"

create_issue "M-9" "中" "Docker イメージの最終実行ユーザーが root" "$(cat <<'EOF'
## 概要

Docker コンテナの PID 1 が root で起動する。

## 深刻度

**中** — コンテナ特権

## 該当箇所

- `Dockerfile:23-29`
- `docker-entrypoint.sh:4-8`

## 問題の説明

ビルド後 `USER root` に戻り、PID 1 は root で起動。entrypoint 内で `runuser` により権限降下するが、コンテナエスケープ時の影響範囲が拡大。

## 対処方法

1. 最終 `USER appuser` に固定
2. `/var/log/vea` の所有権はビルド時または init コンテナで設定

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-9）
EOF
)"

create_issue "M-10" "中" "WEB_RESEARCH_ENABLED=true がデフォルト" "$(cat <<'EOF'
## 概要

WEB 調査機能がデフォルトで有効。API キー設定時に外部へデータ送信される。

## 深刻度

**中** — データ漏洩（外部送信）

## 該当箇所

- `src/vcenter_event_assistant/settings.py:330-336`
- `.env.example:156`

## 問題の説明

API キー設定時、イベント種別文字列が外部検索 API（Tavily/Firecrawl）へ送信される。閉域網想定でもキー設定だけでデータが外部に出うる。

## 対処方法

1. デフォルト `false` に変更
2. 本番では明示オプトイン
3. 閉域網向けドキュメントを整備

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-10）
EOF
)"

create_issue "M-11" "中" "LangSmith トレーシングによる外部データ送信" "$(cat <<'EOF'
## 概要

LangSmith 有効時に LLM プロンプト（運用データ含む）が外部送信される。

## 深刻度

**中**（有効時） — データ漏洩（外部送信）

## 該当箇所

- `src/vcenter_event_assistant/services/llm/llm_tracing.py`
- `src/vcenter_event_assistant/settings.py:464-467`
- `.env.example:109-113`

## 問題の説明

`LANGSMITH_TRACING_ENABLED=true` 時、LLM プロンプト（イベント/ホスト情報含む）が LangSmith へ送信される。

## 対処方法

1. 本番デフォルト OFF
2. 有効化時の起動 WARNING
3. データ分類ポリシーの文書化

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-11）
EOF
)"

create_issue "M-12" "中" "依存パッケージの既知脆弱性" "$(cat <<'EOF'
## 概要

`cryptography` および `langchain-core` に既知 CVE がある。

## 深刻度

**中** — 依存関係の脆弱性

## 該当箇所

- `pyproject.toml:16,21`（`cryptography>=46.0.6`, `langchain-core>=1.2.25`）

## 問題の説明

`cryptography` 46.0.6 には複数 CVE（修正版 46.0.7〜50.0.0）。vCenter パスワード暗号化に使用。`langchain-core` 1.2.25 にも CVE 報告あり（現コードでは影響 API 未使用だが依存として存在）。

## 対処方法

1. `cryptography>=50.0.0`、`langchain-core>=1.2.28` 等へ更新し `uv lock` 再生成
2. CI に `pip-audit` / `npm audit` を追加

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-12）
EOF
)"

create_issue "M-13" "中" "チャット履歴の localStorage 平文保存" "$(cat <<'EOF'
## 概要

フロントエンドがチャット履歴等を localStorage に平文保存している。

## 深刻度

**中** — クライアント側データ保護

## 該当箇所

- `frontend/src/preferences/chatPanelStorage.ts:5-6`
- `frontend/src/hooks/useChatPanelController.ts`

## 問題の説明

最大 1000 件のメッセージ、期間、vCenter ID 等を `localStorage` に平文保存。XSS や共有端末から読み取り可能。

## 対処方法

1. デフォルトを `sessionStorage` またはメモリのみに
2. 永続化が必要ならサーバー側セッション + 暗号化

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-13）
EOF
)"

create_issue "M-14" "中" "CSRF 対策インフラ未整備（将来リスク）" "$(cat <<'EOF'
## 概要

フロントエンド API クライアントに CSRF 対策がない。

## 深刻度

**中**（将来リスク） — CSRF

## 該当箇所

- `frontend/src/api.ts:16-43`

## 問題の説明

変更系 API が素の `fetch` で JSON 送信。Cookie 認証導入時に CSRF 脆弱性となる基盤がない。

## 対処方法

1. Cookie 認証導入時に double-submit トークンまたはカスタムヘッダー必須化
2. `SameSite=Strict` クッキー

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（M-14）
EOF
)"

create_issue "L-1" "低" "平文 HTTP による vCenter 接続を UI が許可" "$(cat <<'EOF'
## 概要

vCenter 登録 UI が HTTP プロトコルを選択可能。

## 深刻度

**低** — 通信の機密性

## 該当箇所

- `src/vcenter_event_assistant/api/schemas/vcenters.py:25`
- `frontend/src/panels/settings/VCentersPanel.tsx`

## 対処方法

本番 UI では HTTPS のみ。HTTP は lab モード限定。

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（L-1）
EOF
)"

create_issue "L-2" "低" "Markdown レンダリングで外部画像読み込み可能" "$(cat <<'EOF'
## 概要

サニタイズ済み Markdown が外部 URL の画像読み込みを許可する。

## 深刻度

**低** — プライバシー / トラッキング

## 該当箇所

- `frontend/src/markdown/gfmSanitizedMarkdownPlugins.ts`

## 対処方法

1. サニタイズスキーマで `img` 禁止、または `src` を `'self'` / data URI のみに制限
2. CSP `img-src` と併用

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（L-2）
EOF
)"

create_issue "L-3" "低" "API エラー本文を UI にそのまま表示" "$(cat <<'EOF'
## 概要

API エラーレスポンス本文が UI にそのまま表示される。

## 深刻度

**低** — 情報漏洩

## 該当箇所

- `frontend/src/api.ts:11,23,36,43`

## 対処方法

ユーザー向けは汎用メッセージ。詳細はサーバーログのみ。

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（L-3）
EOF
)"

create_issue "L-4" "低" "WEB 検索クエリの INFO ログ出力" "$(cat <<'EOF'
## 概要

チャット WEB 検索クエリが INFO レベルでログ出力される。

## 深刻度

**低** — ログへの機密情報

## 該当箇所

- `src/vcenter_event_assistant/services/chat/chat_web_search.py:196,242`

## 対処方法

本番は DEBUG 以下、またはクエリのマスキング/切り詰め。

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（L-4）
EOF
)"

create_issue "L-5" "低" "開発用シードの弱いパスワード" "$(cat <<'EOF'
## 概要

MOCK_MODE / SCREENSHOT_E2E_SEED が弱いパスワードを DB に投入する。

## 深刻度

**低**（本番誤設定時は中）

## 該当箇所

- `src/vcenter_event_assistant/dev/mock_mode_seed.py`
- `src/vcenter_event_assistant/dev/screenshot_e2e_seed.py`

## 対処方法

`APP_ENV=development` 以外では起動拒否。本番 Compose にこれらのフラグを含めない。

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（L-5）
EOF
)"

create_issue "L-6" "低" "MOCK_MODE の本番誤設定ガードなし" "$(cat <<'EOF'
## 概要

本番環境で MOCK_MODE=1 が設定されても起動が継続する。

## 深刻度

**低** — 設定ミス

## 該当箇所

- `src/vcenter_event_assistant/settings.py:133-138`

## 対処方法

本番で `MOCK_MODE=1` なら起動失敗。

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（L-6）
EOF
)"

create_issue "L-7" "低" "アラートルール config のスキーマ未検証" "$(cat <<'EOF'
## 概要

アラートルールの `config` フィールドが任意 JSON として受け入れられる。

## 深刻度

**低** — 入力検証

## 該当箇所

- `src/vcenter_event_assistant/api/schemas/alerts.py`

## 対処方法

`rule_type` 別の discriminated union で厳密バリデーション。

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（L-7）
EOF
)"

create_issue "L-8" "低" "Docker Compose のハードニング不足" "$(cat <<'EOF'
## 概要

Docker Compose にセキュリティハードニングオプションがない。

## 深刻度

**低** — コンテナセキュリティ

## 該当箇所

- `docker-compose.postgres.yml`
- `docker-compose.sqlite.yml`

## 対処方法

`read_only`, `cap_drop`, リソース制限, ヘルスチェック追加。

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（L-8）
EOF
)"

create_issue "L-9" "低" "CI / Docker の依存バージョン未固定" "$(cat <<'EOF'
## 概要

Dockerfile および CI で依存バージョンが未固定（supply chain リスク）。

## 深刻度

**低** — サプライチェーン

## 該当箇所

- `Dockerfile:12`（`uv:latest`）
- `.github/workflows/ci.yml`

## 対処方法

1. ダイジェストまたは固定バージョンで pin
2. GitHub Actions は commit SHA で pin

## 参照

- 監査レポート: `docs/security-audit-report-2026-08-23.md`（L-9）
EOF
)"

echo "Done. Created 28 security issues."
