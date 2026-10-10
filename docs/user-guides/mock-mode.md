# モックモードの使い方（デモ・開発）

vCenter・メール（SMTP）・LLM・WEB 検索 API などの **外部サービスが無い環境**でも、画面と主要操作を試せるモードである。本番運用向けではない。

---

## 1. この文書の対象と読み方

| 目的 | まず読む節 |
|-------------|-----------|
| 画面の操作を確認する | [§2](#2-起動手順) → [§3](#3-画面で確認できること) |
| 取り込みやアラートの動きも見たい | [§4](#4-スケジューラの有無) → [§5](#5-何がモックされるか) |
| 本番設定との違いを知りたい | [§6](#6-注意事項) → [§7](#7-よくある質問と切り分け) |

実装・テスト・モジュール構成の詳細は開発者向けの [development.md（モックモード節）](../development.md#モックモードmock_mode1) を参照する。

---

## 2. 起動手順

前提: [利用開始ガイド](../getting-started.md) どおりに `uv sync` 済みであること。フロントを Vite で開く場合は通常どおり別ターミナルで `npm run dev` も起動する。

### 2.1 `.env` に書く（推奨）

```bash
cp .env.example .env   # 未作成の場合
```

`.env` に次を設定する。

```bash
MOCK_MODE=1
DATABASE_URL=sqlite+aiosqlite:///./data/vea.dev.db

# ログイン用の初期 admin（ユーザーがいない DB のときだけ作られる）
VEA_BOOTSTRAP_ADMIN_USERNAME=admin
VEA_BOOTSTRAP_ADMIN_PASSWORD=demo-admin-password

# 任意: true なら合成イベント／メトリクスを定期追加（false なら起動時シードのみ）
# SCHEDULER_ENABLED=true
```

本番用の `./data/vea.db` は触らない。デモ・開発は `vea.dev.db` を使う（[development.md](../development.md) の DB 使い分け）。

### 2.2 起動

**通常利用（ビルド済み UI を同一オリジンで）**

```bash
(cd frontend && npm run build)
uv run vcenter-event-assistant
```

ブラウザで `http://localhost:8000` を開き、上で設定した初期 admin でログインする（[ログインとロール](authentication.md)）。

**開発用途（Vite）**

```bash
# ターミナル 1
uv run vcenter-event-assistant

# ターミナル 2
cd frontend && npm run dev
```

ブラウザは Vite の URL（既定 `http://localhost:5173`）を開く。

### 2.3 シェルだけで一時指定する場合

```bash
MOCK_MODE=1 DATABASE_URL=sqlite+aiosqlite:///./data/vea.dev.db \
  VEA_BOOTSTRAP_ADMIN_USERNAME=admin VEA_BOOTSTRAP_ADMIN_PASSWORD=demo-admin-password \
  uv run vcenter-event-assistant
```

---

## 3. 画面で確認できること

起動に成功すると、ヘッダ付近に次のバナーが出る。

> モックモード: 外部サービス（vCenter / SMTP / LLM / WEB 検索）には接続しない

| 画面 | 期待できること |
|------|----------------|
| **設定 → vCenter** | デモ用 `mock-demo-vc` が登録済み。**接続テスト**は成功し、製品名に `(mock)` が付く |
| **概要 / イベント / グラフ** | シードされたイベント・ホスト／Datastore メトリクスが表示される |
| **設定 → アラート** | デモ用ルール（イベントスコア型）が入っていることがある |
| **チャット** | API キーなしで固定の「（モック応答）」が返る。WEB 検索 ON でも外部 API は呼ばない |
| **ダイジェスト** | LLM 要約は固定のモック文が付く（キー不要） |

初回起動時にデモデータが自動投入される。同じ DB で再起動しても **二重投入はしない**（冪等）。

---

## 4. スケジューラの有無

| `SCHEDULER_ENABLED` | 挙動 |
|---------------------|------|
| `false`（または未使用で無効にした構成） | 起動時シードのみ。データは静的 |
| `true` | 通常どおり定期ジョブが動くが、収集は **合成データ**。時間とともにイベント／メトリクスが増える |

デモで「取り込み後の一覧更新」まで見せたいときは `SCHEDULER_ENABLED=true` を推奨する。手動取り込み（取り込み API／画面操作がある場合）もモック収集経路を通る。

---

## 5. 何がモックされるか

| 機能 | モック時の挙動 |
|------|----------------|
| vCenter 接続・イベント／メトリクス収集 | pyVmomi を使わず合成データを返す |
| アラートメール | SMTP せず、サーバログに件名などを出し **成功扱い**（通知履歴のチャネルは `mock`） |
| チャット / ダイジェスト LLM | 決定論的な固定テキスト。外部 LLM・Copilot CLI は呼ばない |
| WEB 検索（Tavily / Firecrawl） | 固定のデモ結果。実検索 API は呼ばない |
| LangSmith | トレーシング用コールバックを付けない |

`MOCK_MODE=1` のとき、実キーが `.env` にあっても上記のモック経路が優先される（検索プロバイダのキーがあってもモック検索になる）。WEB 調査自体を止めたい場合だけ `WEB_RESEARCH_ENABLED=false` を明示する。

---

## 6. 注意事項

- **本番・実 vCenter 接続用の設定と併用しない。** デモ用 DB（`vea.dev.db`）と `MOCK_MODE=1` の組み合わせを推奨する。
- モック応答やシードデータは説明用のダミーである。運用判断の根拠にしない。
- Playwright 用の `SCREENSHOT_E2E_SEED=1` とは別機能である。スクリーンショット用の最小シードであり、本モードの代替ではない。
- 認証は既定で有効である（上の手順で初期 admin を作る）。それでもモックモードはデモ用なので、ネットワークに公開しない（[getting-started.md のセキュリティ](../getting-started.md#セキュリティ)）。

---

## 7. よくある質問と切り分け

### バナーが出ない

`MOCK_MODE=1` がプロセスに渡っているか確認する。`.env` 変更後はプロセスの再起動が必要である。`GET /api/config` の `mock_mode` が `true` かも確認できる。

### イベントやグラフが空

別の `DATABASE_URL`（空の DB）を見ていないか確認する。シードは vCenter 名 `mock-demo-vc` が無いときだけ投入される。

### 実 vCenter に切り替えたい

`MOCK_MODE` を外す（または `0` / `false`）にし、実ホストの接続情報と必要なら LLM / SMTP を設定して再起動する。デモ用 DB を使い続けるとデモ行が残るため、本番相当のデータと混ぜない方が安全である。

### メールが届かない

モックモードでは意図的に SMTP しない。送信内容はアプリログに出る。実メールの確認は `MOCK_MODE` をオフにし、`SMTP_HOST` と `ALERT_EMAIL_TO` を設定する。

---

## 8. 関連ドキュメント

| 読者 | ドキュメント |
|------|-------------|
| **利用者（本書）** | 本ファイル |
| **セットアップ・起動** | [getting-started.md](../getting-started.md) |
| **開発者（実装・テスト）** | [development.md（モックモード節）](../development.md#モックモードmock_mode1) |
| **画面操作（モックでも UI は同じ）** | [chat.md](chat.md)、[digests.md](digests.md)、[alerts.md](alerts.md) |
