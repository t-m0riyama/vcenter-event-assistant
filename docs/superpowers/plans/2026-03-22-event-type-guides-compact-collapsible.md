# イベント種別ガイド一覧のコンパクト表示＋折りたたみ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 設定済みのイベント種別ガイド行を**縦に占有しない**ようにし、**折りたたみ可能**にする。折りたたみ時は「一般的な意味・想定される原因・対処方法」を**1つのプレビュー文**にまとめ、**省略表示をデフォルト**（初期状態は閉じたまま）とする。

**Architecture:** ブラウザ標準の `<details>` / `<summary>` で開閉を実装し（追加依存なし）、React の展開状態は原則保持しない（`open` 属性を付けない＝デフォルト閉）。`summary` 内にイベント種別・対処要否の視覚・**連結＋省略プレビュー**を表示。展開時は編集用の既存フィールド（チェックボックス＋3 textarea＋保存・削除）をそのまま配置。プレビュー用の連結・整形は **純関数** に切り出してテスト可能にする。

**Tech Stack:** React / TypeScript / 既存 [`App.css`](../../../frontend/src/App.css) — テーマ変数（`--color-*` / `--spacing-*`）のみ。変更対象は主に [`EventTypeGuidesPanel.tsx`](../../../frontend/src/panels/settings/EventTypeGuidesPanel.tsx)。

---

## スコープ外（YAGNI）

- **「追加」フォーム**のレイアウト変更（一覧の可読性が主目的のため現状維持でよい）
- バックエンド・API・Zod の変更
- 開閉状態の永続化（localStorage 等）
- 一覧の「追加」セクションと同じテーブルレイアウトの維持（必要なら `<table>` → ブロックリストへ変更するが、API 非依存）

---

## ファイル構成

| 役割 | パス |
|------|------|
| UI（一覧のマークアップ差し替え） | [`frontend/src/panels/settings/EventTypeGuidesPanel.tsx`](../../../frontend/src/panels/settings/EventTypeGuidesPanel.tsx) |
| プレビュー文生成（推奨） | **新規** `frontend/src/panels/settings/EventTypeGuideCollapsedPreview.ts` — 連結＋最大文字数で切り詰め（末尾は `…`） |
| プレビュー単体テスト（推奨） | **新規** `frontend/src/panels/settings/EventTypeGuideCollapsedPreview.test.ts`（Vitest） |
| スタイル | [`frontend/src/App.css`](../../../frontend/src/App.css) — `.event-type-guides-*` を一覧用に拡張（折りたたみ行・summary 内レイアウト・プレビュー `line-clamp`） |

---

## 仕様の詳細（実装者向け）

1. **折りたたみ:** 各行を `<details class="event-type-guide-row">` とし、**`open` 属性を付けない**（デフォルト閉）。キーボード・スクリーンリーダーはネイティブ挙動に任せる。

2. **summary 内の表示（省略）:**
   - 1 行目: `event_type`（長い場合は `word-break` / `overflow` で既存 `.msg` に近い扱い）
   - 対処要否（`action_required`）のバッジまたは短いラベル（例:「要対処」）— 既存の `event-row--action-required` と色を揃えず、**設定パネル用の小さなクラス**を新設してよい
   - プレビュー: `draft` の `general_meaning` / `typical_causes` / `remediation` を **短いラベル付きで連結**（例: `意味: … / 原因: … / 対処: …`）し、**空のみの項目はスキップ**。全文が空なら `（本文なし）` のようなプレースホルダ
   - **論理省略:** プレビュー関数で **文字数上限**（例: 200 文字）に切り詰め、末尾に `…`。単体テストはこの文字列をアサートする
   - **視覚省略:** CSS で `line-clamp: 2`（等）を併用し、極端に長い1行やブラウザ幅でも summary が縦に膨らみすぎないようにする。**意図:** 文字列は関数側で主に制御し、`line-clamp` はレイアウト上の保険（論理と見た目がわずかにずれても許容）

3. **展開時（`<details>` の子）:** 現状と同じ編集 UI（対処が必要チェック、3 つの textarea、**保存・削除**）。配置は縦並びのままでよい。

4. **保存・削除ボタンの配置（決定）:** **`summary` にはボタンを置かない。** **保存**と**削除**（`confirm` は現状どおり）は**展開された子領域のみ**に配置する。閉じたまま削除できないが、`<summary>` 内クリックで `<details>` が開閉する挙動と **ボタン誤クリック・イベント伝播**の問題を避けられる。誤削除対策にもなる。

5. **`<summary>` 内に将来インタラクティブ要素を置く場合:** やむを得ず `<summary>` 内に `button` 等を置く場合は **`type="button"`** と、クリックで `<details>` がトグルされないよう **`onClick` で `event.stopPropagation()`**（必要なら `preventDefault`）を検討する。本タスクの既定構成（summary は非ボタン）では必須ではない。

6. **マークアップ:** `<table>` の `<tbody>` 内に `<details>` を入れると HTML として無効になりやすい。**推奨:** 一覧を `<div class="event-type-guides-list">` のリスト（または `<ul>`）に変更し、各行を `<li>` / `<details>` で表現。見出し「一覧」は維持し、視覚的に表らしく CSS でグリッドまたはボーダーを付ける。

7. **アクセシビリティ（任意）:** `summary` が情報量が多い場合、**`aria-label`** で「イベント種別名＋要対処の有無」を短くまとめるとスクリーンリーダーで一覧しやすい。

---

## Task 1: プレビュー用純関数とテスト（TDD 可）

**Files:**

- Create: `frontend/src/panels/settings/EventTypeGuideCollapsedPreview.ts`
- Create: `frontend/src/panels/settings/EventTypeGuideCollapsedPreview.test.ts`（推奨）

- [ ] **Step 1:** 失敗するテストを書く（例: 3 フィールドすべてに値があるとき連結される、空はスキップ、合計が長いとき `max` 文字で `…`）

```typescript
// 例（実装はテストに合わせて調整）
import { describe, it, expect } from 'vitest'
import { formatEventTypeGuideCollapsedPreview } from './EventTypeGuideCollapsedPreview'

describe('formatEventTypeGuideCollapsedPreview', () => {
  it('連結する', () => {
    const s = formatEventTypeGuideCollapsedPreview(
      { general_meaning: 'a', typical_causes: 'b', remediation: 'c' },
      { maxChars: 200 },
    )
    expect(s).toContain('a')
    expect(s).toContain('b')
  })
})
```

- [ ] **Step 2:** `cd frontend && npm test` で実行（`frontend/package.json` の `test` は `vitest run` のため **`npm test -- --run` は不要**）

- [ ] **Step 3:** 純関数を実装してグリーンにする

- [ ] **Step 4:** コミットは**任意**（小さく刻むか、Task 4 完了時にまとめて 1 コミットでもよい）

---

## Task 2: EventTypeGuidesPanel の一覧を details ベースに変更

**Files:**

- Modify: `frontend/src/panels/settings/EventTypeGuidesPanel.tsx`

- [ ] **Step 1:** 一覧の `<table>` をやめ、`list.map` で `<details>` 行を返す構造に置換（`key={r.id}` は `details` に付与）

- [ ] **Step 2:** `summary` に `event_type`、プレビュー（`formatEventTypeGuideCollapsedPreview(draft[r.id] ?? rowToDraft(r), …)`）、`action_required` の表示（**ボタンは置かない**）

- [ ] **Step 3:** 子領域に既存の `<label>` + textarea 群と**保存・削除**ボタン

- [ ] **Step 4:** `cd frontend && npm test` と `npm run build` で型・ビルド確認

---

## Task 3: App.css の調整

**Files:**

- Modify: `frontend/src/App.css`

- [ ] **Step 1:** `.event-type-guides-table` を廃止またはリスト用クラス（例: `.event-type-guides-list`）に付け替え、行間・ボーダー、summary の flex 配置

- [ ] **Step 2:** プレビュー用クラスに `line-clamp`、フォントサイズ（`var(--font-size-caption2)` 等）を指定

- [ ] **Step 3:** 既存の `.event-type-guides-edit-cells` は展開内のラッパに継承利用可能

---

## Task 4: 検証

- [ ] **Step 1:** `cd frontend && npm test && npm run build`

- [ ] **Step 2:** 手動: 一覧が初期で閉じていること、プレビューが意味・原因・対処を含むこと、展開で編集・保存できること、削除が動くこと

- [ ] **Step 3:** Conventional Commits（例: `feat(frontend): compact collapsible event type guide list`）

---

## 計画レビュー

`plan-document-reviewer` によるレビュー反映済み（2026-03-22）。反映内容: `open` 属性の表記修正、保存/削除は展開領域のみに決定、`summary` 内ボタン時の注意、論理省略と `line-clamp` の役割分担、`npm test` コマンド、コミット粒度の任意化。

---

## 実行の選び方

プラン承認後:

1. **Subagent-Driven（推奨）** — タスクごとにサブエージェント + レビュー
2. **Inline Execution** — 同一セッションで `executing-plans` に沿って一括実行

どちらで進めるか指定してください。
