# イベント種別ガイド（公式ドキュメント調査ベース）コンテンツ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推奨）または `superpowers:executing-plans` でタスク単位に実装。チェックボックス（`- [ ]`）で進捗管理。

**Goal:** Broadcom／VMware 公式ドキュメントを根拠に、既存の `vea-event-type-guides` 形式の **シード JSON** と、継続メンテ用の **日本語運用ドキュメント（出典表つき）** をリポジトリに追加する（第1弾は **優先サブセット数十件**、拡張はバックログで管理）。

**Architecture:** 優先リストは **① 収集済みイベント DB 由来**（[`GET /api/event-types`](../../../src/vcenter_event_assistant/api/routes/events.py)、ダッシュボード [`dashboard_summary`](../../../src/vcenter_event_assistant/api/routes/dashboard.py) の上位種別）と **② 障害調査で頻出する定番カテゴリ**をマージして決定する。**本文は要約**し、**転載ではなく出典 URL を別ファイル（Markdown 表）で管理**する。JSON は既存 Zod（[`eventTypeGuidesFileSchema`](../../../frontend/src/api/schemas.ts)）で検証可能な形に固定し、**スキーマ拡張は行わない**（`source_url` 等は将来別タスク）。

**Tech Stack:** JSON / Markdown（日本語）/ Vitest（[`eventTypeGuidesFileSchema`](../../../frontend/src/api/schemas.ts) によるシード検証）/ 既存 API・UI（インポートは [`EventTypeGuidesPanel`](../../../frontend/src/panels/settings/EventTypeGuidesPanel.tsx)）

**関連仕様:** ブレインストーミング合意（シード＋運用ドキュメント、優先サブセット、ハイブリッド方針）。コード変更を伴う JSON 入出力仕様は [`2026-03-22-event-type-guides-json-import-export.md`](./2026-03-22-event-type-guides-json-import-export.md) を参照。

**推奨コンテキスト:** 可能なら専用 git worktree で作業（`superpowers:using-git-worktrees`）。必須ではない。

---

## ファイル構成（新規）

| 役割 | パス |
|------|------|
| シード JSON（第1弾・取り込み用） | 新規 [`data/seed/event-type-guides-priority-v1.json`](../../../data/seed/event-type-guides-priority-v1.json) |
| 運用手順・記入ルール（日本語） | 新規 [`docs/event-type-guides/README.md`](../../../docs/event-type-guides/README.md) |
| 出典・参照日テーブル（イベント種別ごと） | 新規 [`docs/event-type-guides/citations-priority-v1.md`](../../../docs/event-type-guides/citations-priority-v1.md) |
| 優先リスト決定メモ（任意・短く） | 新規 [`docs/event-type-guides/priority-list-rationale.md`](../../../docs/event-type-guides/priority-list-rationale.md) |
| シードがスキーマに適合するかのテスト | 変更 [`frontend/src/api/eventTypeGuidesFile.test.ts`](../../../frontend/src/api/eventTypeGuidesFile.test.ts) |

**変更しないもの:** DB モデル、API、Zod スキーマ（本計画は **データとドキュメントのみ**）。

---

## JSON シードの必須形状（確定）

[`eventTypeGuidesFileSchema`](../../../frontend/src/api/schemas.ts) に準拠:

- `format`: `"vea-event-type-guides"`
- `version`: 整数 `1`
- `exportedAt`: ISO 文字列（任意）
- `guides`: 配列。要素ごとに `event_type`（1〜512 文字、前後空白はフロント側で trim）、`general_meaning` / `typical_causes` / `remediation`（各最大 8000 文字または null）、`action_required`（boolean）
- `guides` 内の `event_type` **重複禁止**

---

## Task 1: ディレクトリと空のシード雛形

**Files:**

- 新規: [`data/seed/event-type-guides-priority-v1.json`](../../../data/seed/event-type-guides-priority-v1.json)
- 新規: [`docs/event-type-guides/README.md`](../../../docs/event-type-guides/README.md)（骨子のみで可）

- [ ] **Step 1: `data/seed` と `docs/event-type-guides` を作成し、検証用の最小 JSON を置く**

最小例（`guides` は空配列でよい。後続 Task で追記）:

```json
{
  "format": "vea-event-type-guides",
  "version": 1,
  "exportedAt": "2026-03-22T00:00:00.000Z",
  "guides": []
}
```

- [ ] **Step 2: README に「目的」「インポート手順（設定 → イベント種別ガイド → インポート）」「公式情報の要約方針（長文転載禁止・出典は citations へ）」の見出しだけ置く**

- [ ] **Step 3: Commit**

```bash
git add data/seed/event-type-guides-priority-v1.json docs/event-type-guides/README.md
git commit -m "docs: add event type guides seed scaffold and readme skeleton"
```

---

## Task 2: 失敗するテスト（シードファイルの Zod 検証）

**Files:**

- 変更: [`frontend/src/api/eventTypeGuidesFile.test.ts`](../../../frontend/src/api/eventTypeGuidesFile.test.ts)

- [ ] **Step 1: シード JSON を読み込み `eventTypeGuidesFileSchema.parse` するテストを追加する**

`import.meta.url` と `node:fs` / `node:path` でリポジトリルートの [`data/seed/event-type-guides-priority-v1.json`](../../../data/seed/event-type-guides-priority-v1.json) を読む例:

```typescript
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { eventTypeGuidesFileSchema } from './schemas'

const here = dirname(fileURLToPath(import.meta.url))

describe('data/seed/event-type-guides-priority-v1.json', () => {
  it('parses with eventTypeGuidesFileSchema', () => {
    const path = join(here, '../../../data/seed/event-type-guides-priority-v1.json')
    const raw = JSON.parse(readFileSync(path, 'utf-8'))
    const parsed = eventTypeGuidesFileSchema.parse(raw)
    expect(parsed.format).toBe('vea-event-type-guides')
  })
})
```

- [ ] **Step 2: テスト実行**

Run（リポジトリルートから）:

```bash
cd frontend && npm run test -- src/api/eventTypeGuidesFile.test.ts
```

Expected: **PASS**（空 `guides` でもスキーマは通る）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/eventTypeGuidesFile.test.ts
git commit -m "test: validate event type guides seed json with zod"
```

---

## Task 3: 出典表テンプレと citations ファイル

**Files:**

- 新規: [`docs/event-type-guides/citations-priority-v1.md`](../../../docs/event-type-guides/citations-priority-v1.md)

- [ ] **Step 1: 次の列を持つ表テンプレを作成する（日本語の説明行つき）**

  - `event_type`（アプリと完全一致）
  - `参照 URL`（公式ドキュメントまたは KB）
  - `参照日`（YYYY-MM-DD）
  - `メモ`（どの節を根拠にしたか、一言）

- [ ] **Step 2: Commit**

```bash
git add docs/event-type-guides/citations-priority-v1.md
git commit -m "docs: add citations table template for event type guides"
```

---

## Task 4: 優先リストの確定と rationale メモ

**Files:**

- 新規または変更: [`docs/event-type-guides/priority-list-rationale.md`](../../../docs/event-type-guides/priority-list-rationale.md)

- [ ] **Step 1: 実環境またはステージングで `GET /api/event-types?limit=500` の結果から上位をメモする**（トークン・URL はコミットしない）

- [ ] **Step 2: ダッシュボード要約の「イベント種別トップ」と突き合わせ、第1弾に含める `event_type` の一覧（数十件目安）を rationale に列挙する**

- [ ] **Step 3: 定番カテゴリ（例: ストレージ／ネットワーク／vMotion／HA など）で補完する場合は、その理由を1文で書く**

- [ ] **Step 4: Commit**

```bash
git add docs/event-type-guides/priority-list-rationale.md
git commit -m "docs: document priority event types for guide seed v1"
```

---

## Task 5: 公式ドキュメント調査とシード本文の投入（第1弾）

**Files:**

- 変更: [`data/seed/event-type-guides-priority-v1.json`](../../../data/seed/event-type-guides-priority-v1.json)
- 変更: [`docs/event-type-guides/citations-priority-v1.md`](../../../docs/event-type-guides/citations-priority-v1.md)
- 変更: [`docs/event-type-guides/README.md`](../../../docs/event-type-guides/README.md)

- [ ] **Step 1: 対象 vSphere バージョンを README に固定で記載する**（例: 「本シードは vSphere 8.x 系ドキュメントを主に参照」）

- [ ] **Step 2: 各 `event_type` について Broadcom／VMware 公式（製品ドキュメント、API リファレンス、該当する KB）を調査し、`general_meaning` / `typical_causes` / `remediation` を **日本語で要約**して JSON に追記する**

- [ ] **Step 3: `action_required` を運用定義に沿って設定する**（曖昧なら README に判断基準を追記）

- [ ] **Step 4: 各種別の出典を `citations-priority-v1.md` に1行以上追加する**

- [ ] **Step 5: テスト実行**

```bash
cd frontend && npm run test -- src/api/eventTypeGuidesFile.test.ts
```

Expected: **PASS**

- [ ] **Step 6: （任意）ローカルで API 起動後、UI からインポートし一覧表示を確認**

- [ ] **Step 7: Commit**

```bash
git add data/seed/event-type-guides-priority-v1.json docs/event-type-guides/
git commit -m "docs: populate priority v1 event type guides from official docs"
```

---

## Task 6: README 完成（運用・更新・拡張）

**Files:**

- 変更: [`docs/event-type-guides/README.md`](../../../docs/event-type-guides/README.md)

- [ ] **Step 1: 次を日本語で記載する**

  - 調査の推奨手順（公式サイトの検索キーワード、`event_type` 文字列との対応の取り方）
  - レビュー観点（用語統一、`event_type` 表記揺れ、空欄の扱い）
  - マイナーバージョンアップ時の差分確認手順
  - 第2弾（数百件）に広げる際のバックログ運用（`priority-v2` を別ファイルにする等）

- [ ] **Step 2: Commit**

```bash
git add docs/event-type-guides/README.md
git commit -m "docs: complete event type guides maintenance readme"
```

---

## Plan Review Loop

1. 本書を `plan-document-reviewer` サブエージェントに渡し、次を含む **短いレビューコンテキスト**を添える（セッション履歴は渡さない）:
   - 計画ファイル: [`docs/superpowers/plans/2026-03-22-event-type-guides-official-docs-content.md`](./2026-03-22-event-type-guides-official-docs-content.md)
   - 関連仕様: 本書冒頭の Goal／Architecture、および [`2026-03-22-event-type-guides-json-import-export.md`](./2026-03-22-event-type-guides-json-import-export.md)
2. 指摘があれば修正し、最大 3 回まで再レビュー。それ以上は人間にエスカレーション。

---

## Execution Handoff

計画書は [`docs/superpowers/plans/2026-03-22-event-type-guides-official-docs-content.md`](./2026-03-22-event-type-guides-official-docs-content.md) に保存済み。

**実行オプション:**

1. **Subagent-Driven（推奨）** — タスクごとに新しいサブエージェントを起動し、タスク間でレビューする（`superpowers:subagent-driven-development`）。
2. **Inline Execution** — 同一セッションでチェックポイント付きバッチ実行（`superpowers:executing-plans`）。

どちらで進めるか指定してください。
