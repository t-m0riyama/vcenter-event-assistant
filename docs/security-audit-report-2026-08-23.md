# セキュリティ監査レポート

**対象リポジトリ:** vcenter-event-assistant  
**監査日:** 2026-08-23  
**監査範囲:** バックエンド（Python/FastAPI）、フロントエンド（React/TypeScript）、Docker/CI 設定、依存関係

## 監査方針

- 静的コードレビューおよび設定ファイルの確認に基づく。
- **除外事項:** 認証をリバースプロキシに委ねる設計自体は問題点として扱わない（ユーザー指定）。ただし、認証の有無に関わらず成立する脆弱性（SSRF、平文保存、DoS 等）は報告対象とする。
- 本番環境ではリバースプロキシによるネットワーク分離・アクセス制御が前提である場合、一部のリスクは緩和される。各項目に「前提条件」を明記する。

---

## エグゼクティブサマリー

| 深刻度 | 件数 |
|--------|------|
| 高     | 5    |
| 中     | 14   |
| 低     | 9    |

**最優先で対処すべき項目:**

1. vCenter ホスト設定を悪用した **SSRF**（サーバー側から任意ホストへの接続）
2. `VEA_SECRET_KEY` 未設定時の **vCenter パスワード平文 DB 保存**
3. vCenter TLS 検証 **デフォルト OFF**（MITM リスク）
4. Docker Compose / 設定の **弱いデフォルト DB パスワード**
5. **`POST /api/chat/preview`** による運用データの情報漏洩

SQL インジェクション、パストラバーサル（SPA 静的配信）、Markdown XSS 対策など、いくつかの領域では適切な実装が確認された（「問題なし」セクション参照）。

---

## 高（Critical / High）

### H-1. SSRF — vCenter ホスト設定経由の任意宛先接続

| 項目 | 内容 |
|------|------|
| **深刻度** | 高 |
| **カテゴリ** | SSRF / ネットワーク攻撃 |
| **該当箇所** | `src/vcenter_event_assistant/api/schemas/vcenters.py:24`, `api/routes/vcenters.py:97-128`, `collectors/connection.py:53-77` |
| **説明** | vCenter 作成・更新 API で `host` に任意文字列（最大 512 文字）を設定可能。プライベート IP、ループバック、クラウドメタデータ（`169.254.169.254`）等のブロックがない。接続テスト（`GET /api/vcenters/{id}/test`）および手動/定期インジェストがサーバーから当該ホストへ TCP 接続する。`http` / `https` 両方が許可される。 |
| **前提条件** | API に到達可能な攻撃者（リバースプロキシ内側の悪意ある利用者、誤設定による公開等） |
| **対処方法** | ① `host` を FQDN パターンまたは許可サフィックス（`VCENTER_ALLOWED_HOST_SUFFIXES`）で検証。② プライベート IP・リンクローカル・メタデータ IP を拒否。③ 本番では egress ファイアウォールで vCenter 向け以外の送信を制限。④ 接続テストを管理者限定エンドポイントに分離する。 |

---

### H-2. vCenter パスワードの平文 DB 保存（`VEA_SECRET_KEY` 未設定時）

| 項目 | 内容 |
|------|------|
| **深刻度** | 高 |
| **カテゴリ** | 機密情報の保護 |
| **該当箇所** | `src/vcenter_event_assistant/db/encrypted_string.py:73-81`, `settings.py:108-113`, `.env.example:18-22`, `docker-compose.postgres.yml:24-25` |
| **説明** | `VEA_SECRET_KEY` が未設定の場合、vCenter パスワードは DB に平文で保存・読み取りされる。起動時 WARNING のみで処理は継続。Compose テンプレートでも鍵設定がコメントアウトされており、本番で暗号化なし運用になりやすい。 |
| **前提条件** | DB バックアップ、ボリューム、SQL ダンプ等への不正アクセス |
| **対処方法** | ① 本番起動時に `VEA_SECRET_KEY` 未設定なら **起動失敗**（`APP_ENV=production` 等で分岐）。② Compose / `.env.example` で鍵設定を必須化し、生成手順を明記。③ 鍵未設定時は vCenter 作成・更新 API を拒否。④ DB ボリュームの暗号化（at-rest encryption）をインフラ側で適用。 |

---

### H-3. vCenter TLS 証明書検証がデフォルト OFF

| 項目 | 内容 |
|------|------|
| **深刻度** | 高 |
| **カテゴリ** | 通信の機密性・完全性 |
| **該当箇所** | `api/schemas/vcenters.py:29`, `db/models.py:23`, `collectors/connection.py:47-49`, `frontend/src/panels/settings/VCentersPanel.tsx:30,45,75` |
| **説明** | 新規 vCenter 登録のデフォルトが `verify_ssl=False`。`ssl.CERT_NONE` となり MITM により vCenter 認証情報やイベントデータが窃取される可能性がある。フロントエンド UI も同様にデフォルト OFF。 |
| **前提条件** | 同一ネットワーク上の攻撃者、または侵害された中間装置 |
| **対処方法** | ① バックエンド・フロントエンドとも **デフォルト `verify_ssl=true`** に変更。② 検証スキップは明示的オプトイン（「ラボ/開発のみ」警告付き）。③ プライベート CA 利用時は `VCENTER_CA_BUNDLE` の設定手順をドキュメント化。 |

---

### H-4. 弱いデフォルト DB パスワード

| 項目 | 内容 |
|------|------|
| **深刻度** | 高 |
| **カテゴリ** | 認証情報 / 設定ミス |
| **該当箇所** | `docker-compose.postgres.yml:6,23`, `settings.py:32-33`, `.env.example:6,26` |
| **説明** | Docker Compose は `POSTGRES_PASSWORD` 未設定時に `vea` を使用。アプリ設定のフォールバックは `postgres:postgres@localhost`。コピペによる本番デプロイで推測可能な認証情報が残る。 |
| **前提条件** | DB ポートへの到達（Compose では Postgres はホスト非公開だが、同一 Docker ネットワークからは到達可能） |
| **対処方法** | ① Compose で `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD を設定してください}` のように **フォールバックを削除**。② `settings.py` からハードコード認証情報を除去し、未設定時は起動失敗。③ `.env.example` の `changeme` / `postgres:postgres` をプレースホルダーに置換。 |

---

### H-5. チャットプレビュー API による運用データの情報漏洩

| 項目 | 内容 |
|------|------|
| **深刻度** | 高 |
| **カテゴリ** | 情報漏洩 |
| **該当箇所** | `api/routes/chat.py:94-117` |
| **説明** | `POST /api/chat/preview` は LLM 呼び出し不要で、集約イベント、ホスト名、メトリクス、会話履歴を含む `context_block` を返す。`LLM_ANONYMIZATION_ENABLED=false`（開発向け）では実名が含まれる。LLM 設定チェックもない。 |
| **前提条件** | API に到達可能な任意の呼び出し元 |
| **対処方法** | ① 本番では `PREVIEW_API_ENABLED=false`（デフォルト OFF）で無効化。② 開発環境限定フラグで保護。③ 匿名化を preview でも強制。④ ネットワーク ACL と併用。 |

---

## 中（Medium）

### M-1. レート制限の欠如（DoS / リソース枯渇）

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `main.py`, `api/routes/chat.py`, `api/routes/ingest.py`, `api/routes/digests.py` |
| **説明** | LLM チャット、手動インジェスト、ダイジェスト生成、重い DB 集約 API にアプリケーションレベルのレート制限・同時実行数上限がない。 |
| **対処方法** | slowapi 等のミドルウェア、リバースプロキシでの rate limit、LLM/インジェストのグローバル同時実行キャップ、`429 Too Many Requests` 応答。 |

---

### M-2. アラート履歴 API のページネーション未制限

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `api/routes/alerts.py:175-191` |
| **説明** | `limit` / `offset` に上下限がなく、巨大な `limit` でメモリ枯渇を誘発可能。他ルート（例: `digests.py:45-46`）は `Query(ge=1, le=200)` を使用。 |
| **対処方法** | `limit: Annotated[int, Query(ge=1, le=200)] = 50` 等を適用。 |

---

### M-3. チャット系 API の時間範囲上限なし（DoS）

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `api/schemas/chat.py:18-25`, `services/chat/chat_context_payloads.py:55-69` |
| **説明** | `from < to` の検証のみ。最大期間の制限がなく、数年分の範囲指定で大規模 DB スキャンが可能。`/api/events/rate-series` には `EVENT_RATE_MAX_BUCKETS` ガードがあるが、チャット系には同等の制限がない。 |
| **対処方法** | 最大期間（例: 30〜90 日）を設定し、超過時は `422` を返す。 |

---

### M-4. インポート API による全件削除

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `api/routes/alerts.py:136-141`, `event_type_guides.py:88-93`, `event_score_rules.py:80-85` |
| **説明** | `delete_*_not_in_import=true` かつ空のインポートリストで `DELETE` が WHERE 句なしの全件削除になる。 |
| **対処方法** | 空リスト + 削除フラグの組み合わせを拒否。別途「purge」エンドポイント + 確認トークンを要求。 |

---

### M-5. HTTP セキュリティヘッダー / CSP 未設定

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `main.py:95-105`, `frontend/index.html` |
| **説明** | API には `Cache-Control: no-store` のみ。CSP、`X-Frame-Options`、`X-Content-Type-Options`、HSTS がない。XSS 発生時の防御層が薄い。 |
| **対処方法** | ミドルウェアまたはリバースプロキシでヘッダー付与。CSP は report-only から段階的導入。 |

---

### M-6. OpenAPI ドキュメントが本番でも公開

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `main.py:84` |
| **説明** | `/docs`, `/redoc`, `/openapi.json` が常時有効。攻撃面の列挙が容易。 |
| **対処方法** | 本番では `docs_url=None, redoc_url=None, openapi_url=None`。または内部ネットワーク限定。 |

---

### M-7. CORS 設定が過剰に寛容

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `main.py:86-93`, `settings.py:105-107` |
| **説明** | `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`。`CORS_ORIGINS` の誤設定時に credentialed クロスオリジンリクエストを許容しうる。 |
| **対処方法** | 必要なメソッド・ヘッダーのみ許可。Cookie 未使用なら `allow_credentials=False`。本番 `CORS_ORIGINS` を明示設定。 |

---

### M-8. 全インターフェースへのバインド（`0.0.0.0`）

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `__init__.py:15`, `docker-compose.postgres.yml:18-19` |
| **説明** | Uvicorn が `0.0.0.0:8000` で待受。Compose は `8000:8000` でホスト全 IF に公開。 |
| **対処方法** | リバースプロキシ同梱時は `127.0.0.1:8000:8000`。`UVICORN_HOST` 環境変数で制御可能にする。 |

---

### M-9. Docker イメージの最終実行ユーザーが root

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `Dockerfile:23-29`, `docker-entrypoint.sh:4-8` |
| **説明** | ビルド後 `USER root` に戻り、PID 1 は root で起動。entrypoint 内で `runuser` により権限降下するが、コンテナエスケープ時の影響範囲が拡大。 |
| **対処方法** | 最終 `USER appuser` に固定。`/var/log/vea` の所有権はビルド時または init コンテナで設定。 |

---

### M-10. `WEB_RESEARCH_ENABLED=true` がデフォルト

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `settings.py:330-336`, `.env.example:156` |
| **説明** | API キー設定時、イベント種別文字列が外部検索 API（Tavily/Firecrawl）へ送信される。閉域網想定でもキー設定だけでデータが外部に出うる。 |
| **対処方法** | デフォルト `false` に変更。本番では明示オプトイン。閉域網向けドキュメントを整備。 |

---

### M-11. LangSmith トレーシングによる外部データ送信

| 項目 | 内容 |
|------|------|
| **深刻度** | 中（有効時） |
| **該当箇所** | `services/llm/llm_tracing.py`, `settings.py:464-467`, `.env.example:109-113` |
| **説明** | `LANGSMITH_TRACING_ENABLED=true` 時、LLM プロンプト（イベント/ホスト情報含む）が LangSmith へ送信される。 |
| **対処方法** | 本番デフォルト OFF。有効化時の起動 WARNING。データ分類ポリシーの文書化。 |

---

### M-12. 依存パッケージの既知脆弱性

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `pyproject.toml:16,21`（`cryptography>=46.0.6`, `langchain-core>=1.2.25`） |
| **説明** | `cryptography` 46.0.6 には複数 CVE（修正版 46.0.7〜50.0.0）。vCenter パスワード暗号化に使用。`langchain-core` 1.2.25 にも CVE 報告あり（現コードでは影響 API 未使用だが依存として存在）。 |
| **対処方法** | `cryptography>=50.0.0`、`langchain-core>=1.2.28` 等へ更新し `uv lock` 再生成。CI に `pip-audit` / `npm audit` を追加。 |

---

### M-13. フロントエンド: チャット履歴の localStorage 平文保存

| 項目 | 内容 |
|------|------|
| **深刻度** | 中 |
| **該当箇所** | `frontend/src/preferences/chatPanelStorage.ts:5-6`, `hooks/useChatPanelController.ts` |
| **説明** | 最大 1000 件のメッセージ、期間、vCenter ID 等を `localStorage` に平文保存。XSS や共有端末から読み取り可能。 |
| **対処方法** | デフォルトを `sessionStorage` またはメモリのみに。永続化が必要ならサーバー側セッション + 暗号化。 |

---

### M-14. フロントエンド: CSRF 対策インフラ未整備

| 項目 | 内容 |
|------|------|
| **深刻度** | 中（将来リスク） |
| **該当箇所** | `frontend/src/api.ts:16-43` |
| **説明** | 変更系 API が素の `fetch` で JSON 送信。Cookie 認証導入時に CSRF 脆弱性となる基盤がない。 |
| **対処方法** | Cookie 認証導入時に double-submit トークンまたはカスタムヘッダー必須化。`SameSite=Strict` クッキー。 |

---

## 低（Low）

### L-1. 平文 HTTP による vCenter 接続を UI が許可

| 該当箇所 | `api/schemas/vcenters.py:25`, `VCentersPanel.tsx` |
| **対処** | 本番 UI では HTTPS のみ。HTTP は lab モード限定。 |

### L-2. Markdown レンダリングで外部画像読み込み可能

| 該当箇所 | `frontend/src/markdown/gfmSanitizedMarkdownPlugins.ts` |
| **対処** | サニタイズスキーマで `img` 禁止、または `src` を `'self'` / data URI のみに制限。CSP `img-src` と併用。 |

### L-3. API エラー本文を UI にそのまま表示

| 該当箇所 | `frontend/src/api.ts:11,23,36,43` |
| **対処** | ユーザー向けは汎用メッセージ。詳細はサーバーログのみ。 |

### L-4. WEB 検索クエリの INFO ログ出力

| 該当箇所 | `services/chat/chat_web_search.py:196,242` |
| **対処** | 本番は DEBUG 以下、またはクエリのマスキング/切り詰め。 |

### L-5. 開発用シードの弱いパスワード

| 該当箇所 | `dev/mock_mode_seed.py`, `dev/screenshot_e2e_seed.py` |
| **対処** | `APP_ENV=development` 以外では起動拒否。本番 Compose にこれらのフラグを含めない。 |

### L-6. `MOCK_MODE` の本番誤設定ガードなし

| 該当箇所 | `settings.py:133-138` |
| **対処** | 本番で `MOCK_MODE=1` なら起動失敗。 |

### L-7. アラートルール `config` のスキーマ未検証

| 該当箇所 | `api/schemas/alerts.py` |
| **対処** | `rule_type` 別の discriminated union で厳密バリデーション。 |

### L-8. Docker Compose のハードニング不足

| 該当箇所 | `docker-compose.*.yml` |
| **対処** | `read_only`, `cap_drop`, リソース制限, ヘルスチェック追加。 |

### L-9. CI / Docker の依存バージョン未固定

| 該当箇所 | `Dockerfile:12`（`uv:latest`）, `.github/workflows/ci.yml` |
| **対処** | ダイジェストまたは固定バージョンで pin。Actions は commit SHA で pin。 |

---

## 問題なし（良好な実装）

| 領域 | 評価 |
|------|------|
| **SQL インジェクション** | SQLAlchemy ORM / パラメータ化クエリ。LIKE 検索は `_escape_like_metachars` でエスケープ（`events.py:41-48`）。 |
| **パストラバーサル（SPA）** | `resolve()` + `is_relative_to()` チェック（`main.py:135-140`）。 |
| **XSS（フロントエンド）** | `dangerouslySetInnerHTML` / `innerHTML` 未使用。Markdown は `rehype-sanitize` 適用。 |
| **API レスポンスのパスワード除外** | `VCenterRead` に password フィールドなし（`schemas/vcenters.py:56-67`）。 |
| **シークレットのビルドコンテキスト除外** | `.dockerignore` で `.env`, `*.db` を除外。 |
| **Postgres のホスト公開** | Compose で Postgres ポート未公開（内部ネットワークのみ）。 |
| **本番 npm 依存** | `npm audit --omit=dev` で 0 件（監査時点）。 |
| **危険なデシリアライゼーション** | `pickle`, 非安全 `yaml.load` 等は `src/` に未使用。 |
| **コマンドインジェクション** | API コードに `shell=True` 等なし。 |

---

## 優先対処ロードマップ

### 即時（本番デプロイ前）

1. `VEA_SECRET_KEY` と強固な `POSTGRES_PASSWORD` を必須化
2. vCenter `verify_ssl` デフォルトを `true` に変更
3. SSRF 対策（ホスト検証 + egress 制限）
4. `/api/chat/preview` の本番無効化または保護
5. `cryptography` 等の依存パッケージ更新

### 短期

6. セキュリティヘッダー / CSP 導入
7. レート制限とページネーション上限
8. インポート API の全件削除防止
9. Docker 非 root 実行
10. OpenAPI ドキュメントの本番無効化

### 中期

11. チャット localStorage の見直し
12. `WEB_RESEARCH_ENABLED` デフォルト OFF
13. CI/CD の supply chain 硬化（pin, audit）
14. Docker Compose ハードニング

---

## 付録: 主要調査ファイル一覧

```
src/vcenter_event_assistant/
  main.py, settings.py, __init__.py
  api/routes/{chat,vcenters,alerts,ingest,event_type_guides,event_score_rules}.py
  api/schemas/{vcenters,chat,alerts}.py
  collectors/connection.py
  db/encrypted_string.py
frontend/src/
  api.ts, markdown/gfmSanitizedMarkdownPlugins.ts
  panels/settings/VCentersPanel.tsx
  preferences/chatPanelStorage.ts
Dockerfile, docker-compose.postgres.yml, docker-entrypoint.sh
.env.example, pyproject.toml
```

---

*本レポートはコードベース静的解析に基づく。動的ペネトレーションテストや本番環境固有のネットワーク構成は対象外。*
