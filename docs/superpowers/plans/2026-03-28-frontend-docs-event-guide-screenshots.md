# フロントエンドドキュメント用スクリーンショット（ガイド展開・一覧）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/frontend.md` にイベントタブのガイド展開キャプチャと設定のイベント種別ガイド一覧キャプチャを追加し、すべての `docs/images/*.png` を設計書どおり **同一ピクセル寸法**（固定ビューポート・`fullPage: false`）で再取得できるようにする。

**Architecture:** Playwright の `screenshots.spec.ts` でテスト開始時に `page.setViewportSize` を **固定 `W×H`** に設定し、既存7枚＋新規2枚をすべて `fullPage: false` で保存する。イベント一覧に **ガイド付きイベント**が必要なため、E2E 用サーバー起動時のみ有効な **オプションの DB シード**（環境変数ガード付き）をバックエンドの `lifespan` に追加し、vCenter・イベント種別ガイド・イベント行を最小限挿入する。設定画面の一覧は同一シードで複数ガイド行を載せる。

**Tech Stack:** TypeScript（Playwright）、Python 3.12+（FastAPI／SQLAlchemy）、既存 `uv run` スクリーンショットスクリプト。

**参照仕様:** [`docs/superpowers/specs/2026-03-28-frontend-docs-event-guide-screenshots-design.md`](../../superpowers/specs/2026-03-28-frontend-docs-event-guide-screenshots-design.md)

---

## ファイル対応表（変更の全体像）

| 領域 | 役割 |
|------|------|
| [`src/vcenter_event_assistant/`](../../../src/vcenter_event_assistant/) | `SCREENSHOT_E2E_SEED=1` のときだけ実行する非公開シード関数（VC・ガイド・イベント行の INSERT）。`lifespan` 内 `init_db` の直後に呼ぶ。 |
| [`frontend/playwright.config.ts`](../../../frontend/playwright.config.ts) | `webServer.command` 実行時の環境に **`SCREENSHOT_E2E_SEED=1`** を付与（既存の `DATABASE_URL` / `SCHEDULER_ENABLED=false` と併記）。`--existing` ではサーバー側に同変数が無いのでドキュメントで注意喚起。 |
| [`frontend/e2e/screenshots.spec.ts`](../../../frontend/e2e/screenshots.spec.ts) | 固定 `DOC_SCREENSHOT_WIDTH` / `HEIGHT`（下記）、全キャプチャを `fullPage: false` に変更。新規2ファイル名は **`events-event-type-guide-expanded.png`** と **`settings-event-type-guides-list.png`**（設計書の例に合わせる）。 |
| [`docs/frontend.md`](../../../docs/frontend.md) | 「イベント」にガイド展開の説明と画像。新見出しで設定のイベント種別ガイド一覧を追加。 |
| [`docs/development.md`](../../../docs/development.md) | 出力ファイル表に2行追加。基準寸法・`--existing` 利用時のデータ前提を短く追記。 |
| [`docs/images/*.png`](../../../docs/images/) | 実装後に `uv run scripts/capture_ui_screenshots.py` で再生成（バイナリコミット）。 |

**基準寸法 `W×H` の決め方（仕様との整合）:**

- 設計書は「`events.png` を計測」とあるが、現状の `fullPage: true` では **高さが可変**のため、本実装では **Playwright の `devices['Desktop Chrome'].viewport` と同じ 1280×720** に **全キャプチャを統一**する（`setViewportSize({ width: 1280, height: 720 })`）。
- 初回以降、すべてのドキュメント用 PNG は **1280×720 ピクセル**になる。設計書の「基準ファイル計測」は、**この固定値への移行**として扱う。

---

### Task 1: バックエンド・スクリーンショット用シード

**Files:**

- Create: `src/vcenter_event_assistant/dev/screenshot_e2e_seed.py`（モジュール名は実装で調整可）
- Modify: `src/vcenter_event_assistant/main.py`（`lifespan` 内で `init_db` の後にシードを条件実行）

- [ ] **Step 1: シード関数の仕様を固定する**

環境変数 **`SCREENSHOT_E2E_SEED`** が **`"1"`** のときだけ実行。それ以外は何もしない。

挿入内容（例・実装で確定）:

- `VCenter` 1件（名前は短い識別子）
- `EventTypeGuide` を **複数件**（一覧キャプチャ用。本文は短く、同じ `event_type` に複数行は不可なので **異なる `event_type`** で2〜3件）
- `EventRecord` 1件以上: いずれかのガイドと **一致する `event_type`** を持ち、`vmware_key` はユニーク制約を満たす整数

`session_scope` 等、既存の DB アクセスパターンに合わせる。冪等性: 2回目起動で重複エラーにならないよう、**既にデータがあればスキップ**するか、固定 UUID / 固定 `event_type` で存在チェックしてから INSERT。

- [ ] **Step 2: `lifespan` からシードを呼ぶ**

`await init_db()` の直後、`SCREENSHOT_E2E_SEED` を見て `await seed_screenshot_e2e_data()` のような形で実行。

- [ ] **Step 3: 単体テスト（任意だが推奨）**

`tests/test_screenshot_e2e_seed.py` を新設し、メモリ SQLite + `SCREENSHOT_E2E_SEED=1` で起動相当のコンテキストから **ガイドとイベントが取得できる**ことを `httpx.AsyncClient` で検証する。既存 `conftest` の `client` フィクスチャを流用できるか確認する。

- [ ] **Step 4: Commit**

```bash
git add src/vcenter_event_assistant/dev/screenshot_e2e_seed.py src/vcenter_event_assistant/main.py tests/test_screenshot_e2e_seed.py
git commit -m "feat: optional E2E screenshot DB seed when SCREENSHOT_E2E_SEED=1"
```

---

### Task 2: Playwright にシード用環境変数を渡す

**Files:**

- Modify: `frontend/playwright.config.ts`

- [ ] **Step 1: `webServer` の `command` または `env` に `SCREENSHOT_E2E_SEED=1` を追加**

既存の `DATABASE_URL=sqlite+aiosqlite:///:memory:` と `SCHEDULER_ENABLED=false` を維持したまま、**スクリーンショット用サーバー**だけシードが有効になるようにする（`npx playwright test e2e/screenshots.spec.ts` 経由で起動するプロセスに限定）。

- [ ] **Step 2: Commit**

```bash
git add frontend/playwright.config.ts
git commit -m "chore(e2e): enable screenshot DB seed for playwright webServer"
```

---

### Task 3: `screenshots.spec.ts` の全面更新と新規2枚

**Files:**

- Modify: `frontend/e2e/screenshots.spec.ts`

- [ ] **Step 1: 定数と共通ヘルパ**

ファイル先頭付近に（例）:

```ts
const DOC_SCREENSHOT_WIDTH = 1280
const DOC_SCREENSHOT_HEIGHT = 720
```

テスト本体の最初で:

```ts
await page.setViewportSize({ width: DOC_SCREENSHOT_WIDTH, height: DOC_SCREENSHOT_HEIGHT })
```

- [ ] **Step 2: 既存の `page.screenshot` をすべて `fullPage: false` に変更**

各画面で、主要コンテンツが見えるよう **必要なら** `locator.scrollIntoViewIfNeeded()` を使う（概要・設定など、720px に収まらないパネルはスクロール位置を調整）。

- [ ] **Step 3: イベントタブ・ガイド展開**

「イベント」クリック後、**ガイド列の `表示`** が付いた行の `<details>` を開く。セレクタは **ロール＋名前**を優先（例: テーブル行と `getByRole('group')` / `summary`）。開いた状態で `events-event-type-guide-expanded.png` を `fullPage: false` で保存。展開後に `expect` でガイド本文のラベル（「一般的な意味」など）が見えることを確認。

- [ ] **Step 4: 設定・イベント種別ガイド一覧**

`設定` → `イベント種別ガイド` サブタブ。一覧の **先頭付近**が見えるよう `main` またはリストの `locator` で `scrollIntoViewIfNeeded`。`settings-event-type-guides-list.png` を保存。`expect` でパネル見出しまたは説明文が表示されていることを確認。

- [ ] **Step 5: ローカルでスクリーンショット生成**

```bash
cd /Users/moriyama/git/vcenter-event-assistant
uv run scripts/capture_ui_screenshots.py
```

期待: 終了コード 0。`docs/images/` に **9枚**（既存7＋新規2）があり、画像ビューアで **いずれも 1280×720**。

- [ ] **Step 6: Commit（PNG と spec をまとめる）**

```bash
git add frontend/e2e/screenshots.spec.ts docs/images/*.png
git commit -m "test(e2e): viewport-sized doc screenshots and event guide captures"
```

---

### Task 4: ドキュメント更新

**Files:**

- Modify: `docs/frontend.md`
- Modify: `docs/development.md`

- [ ] **Step 1: `docs/frontend.md`**

「イベント」節に、**ガイド列の「表示」を展開した例**であること、画像パス、短い説明を追加。続けて **設定 → イベント種別ガイド** のサブセクション（一覧のキャプチャ）を追加。設計書どおり、長い画面は **代表のビューポート**である旨を一文入れてよい。

- [ ] **Step 2: `docs/development.md`**

表に `events-event-type-guide-expanded.png` と `settings-event-type-guides-list.png` を追加。**全キャプチャは固定ビューポート（1280×720）**であること、再取得コマンドは従来どおりであることを記載。**`--existing`** で別プロセスの API に向ける場合、**シードは Playwright 組み込みサーバー専用**であり、手元サーバーには **同等のデータ**が必要であることを明記。

- [ ] **Step 3: Commit**

```bash
git add docs/frontend.md docs/development.md
git commit -m "docs: document event guide screenshots and viewport size"
```

---

### Task 5: 検証コマンド（完了チェック）

- [ ] **Step 1: フロントのビルドとスクリーンショット**

```bash
cd /Users/moriyama/git/vcenter-event-assistant/frontend && npm run build && npx playwright test e2e/screenshots.spec.ts
```

期待: 終了コード 0。

- [ ] **Step 2: Python テスト（シードテストを追加した場合）**

```bash
cd /Users/moriyama/git/vcenter-event-assistant && uv run pytest tests/test_screenshot_e2e_seed.py -v
```

期待: すべて PASS。

---

## 計画レビュー

本計画のレビューは `plan-document-reviewer` サブエージェント向けプロンプト（リポジトリに無い場合は人手レビュー）に、次を渡す:

- 計画パス: `docs/superpowers/plans/2026-03-28-frontend-docs-event-guide-screenshots.md`
- 仕様パス: `docs/superpowers/specs/2026-03-28-frontend-docs-event-guide-screenshots-design.md`

---

## 実装後の進め方（ハンドオフ）

計画ファイル保存後、次のいずれかで実装する。

1. **Subagent-Driven（推奨）** — タスクごとにサブエージェントを起動し、タスク間でレビューする。  
2. **インライン実行** — 同一セッションで `executing-plans` に従いチェックポイント付きで進める。

どちらで進めるかは実行者が選ぶ。
