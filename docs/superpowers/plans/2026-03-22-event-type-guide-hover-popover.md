# ガイド列「表示」ホバーで内容ポップアップ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** イベント一覧のガイド列で、**「表示」にマウスオーバーしたとき**に、意味・原因・対処の内容を**ポップアップ（フローティングパネル）**で見られるようにする。

**Architecture:** 既存の `<details>` によるインライン展開は**維持**し（タッチ・キーボードでも内容にアクセス可能）、デスクトップ向けに **ホバー＋`focus-within`（キーボード）** で同一内容を重ねて表示する。マークアップは **DRY** のため、ガイド本文（`dl`）を **1 コンポーネント**に切り出し、`details` 内とポップアップ内で同じコンポーネントを再利用する。ポップアップは **CSS の `position` + ホバー可視化**（追加ライブラリなし）で実装し、スタイルは `--color-*` / `--spacing-*` など既存テーマ変数のみとする。

**Tech Stack:** React / TypeScript / 既存 `App.css` / 新規小さなコンポーネント（`frontend/src/events/` または `frontend/src/components/`）

---

## スコープ外（YAGNI）

- 概要パネル（`SummaryPanel`）の要注意表にガイド列が無い場合は、**本タスクでは対象外**（イベント一覧のみ）。将来同じコンポーネントを流用する想定で **props 化**しておけばよい。
- Radix / Floating UI 等の新規依存追加（CSS で足りる前提）。

---

## ファイル構成

| 役割 | パス |
|------|------|
| ガイド本文（再利用） | **新規** `frontend/src/events/EventTypeGuideBody.tsx` — `EventTypeGuideSnippet` を受け取り `dl` を描画 |
| 一覧セル | **変更** [`frontend/src/panels/events/EventsPanel.tsx`](frontend/src/panels/events/EventsPanel.tsx) — `details` + ホバー用ラッパー + ポップアップ |
| スタイル | **変更** [`frontend/src/App.css`](frontend/src/App.css) — トリガー・ポップアップの配置・z-index・影・最大幅・スクロール |
| 型 | 既存 [`frontend/src/api/schemas.ts`](frontend/src/api/schemas.ts) の `EventTypeGuideSnippet` を import のみ（スキーマ変更なし） |

---

## Task 1: ガイド本文コンポーネントの抽出

**Files:**
- Create: `frontend/src/events/EventTypeGuideBody.tsx`
- Modify: `frontend/src/panels/events/EventsPanel.tsx`

- [ ] **Step 1:** `EventTypeGuideBody` を新規作成する

```tsx
import type { EventTypeGuideSnippet } from '../api/schemas'

export function EventTypeGuideBody({ guide }: { guide: EventTypeGuideSnippet }) {
  return (
    <dl className="event-type-guide-dl">
      <dt>一般的な意味</dt>
      <dd>{guide.general_meaning?.trim() ? guide.general_meaning : '—'}</dd>
      <dt>想定される原因</dt>
      <dd>{guide.typical_causes?.trim() ? guide.typical_causes : '—'}</dd>
      <dt>対処方法</dt>
      <dd>{guide.remediation?.trim() ? guide.remediation : '—'}</dd>
    </dl>
  )
}
```

- [ ] **Step 2:** `EventsPanel` の `<dl className="event-type-guide-dl">` ブロックを `EventTypeGuideBody` に置き換える

- [ ] **Step 3:** `cd frontend && npm test -- --run`（既存テストが通ること）

- [ ] **Step 4:** コミット（例: `refactor(frontend): extract EventTypeGuideBody`）

---

## Task 2: ホバー用マークアップとラッパー

**Files:**
- Modify: `frontend/src/panels/events/EventsPanel.tsx`

- [ ] **Step 1:** `e.type_guide` がある行のセル構造を次のようにする（概念）

```tsx
<td className="event-type-guide-cell">
  <div className="event-type-guide-cell__wrap">
    <details className="event-type-guide-details">
      <summary className="event-type-guide-summary">表示</summary>
      <EventTypeGuideBody guide={e.type_guide} />
    </details>
    <div className="event-type-guide-popover" role="tooltip">
      <EventTypeGuideBody guide={e.type_guide} />
    </div>
  </div>
</td>
```

- `role="tooltip"` は補助的。`summary` に `tabIndex={0}` は通常不要（`<summary>` はフォーカス可能）。

- [ ] **Step 2:** `event-type-guide-popover` は **ラッパー直下**に置き、`summary` ホバー／ラッパー `focus-within` で表示する（CSS は Task 3）

---

## Task 3: ポップアップの CSS

**Files:**
- Modify: `frontend/src/App.css`

- [ ] **Step 1:** `.event-type-guide-cell__wrap` に `position: relative` を付与する

- [ ] **Step 2:** デフォルトで `.event-type-guide-popover` 非表示（`opacity: 0`, `visibility: hidden`, `pointer-events: none` など）。`transition` は任意。

- [ ] **Step 3:** `.event-type-guide-cell__wrap:hover .event-type-guide-popover` および `.event-type-guide-cell__wrap:focus-within .event-type-guide-popover` で表示する（キーボードで `summary` にフォーカスしたときも出るようにする）

- [ ] **Step 4:** ポップアップの見た目: `position: absolute` / `left` or `right`（テーブルからはみ出さないよう `max-width`（例: `min(24rem, 90vw)`））、`z-index`（既存テーブルより上）、`box-shadow`、`background` は `var(--color-background-elevated)`、`border` は `var(--color-border)`、`padding` は `var(--spacing-2)` 等

- [ ] **Step 5:** 長文対策: `.event-type-guide-popover` に `max-height` + `overflow-y: auto`

- [ ] **Step 6:** `summary` にホバーしたときだけ出したい場合は、**ラッパー**ではなく**子セレクタ**で `.event-type-guide-details:hover ~ .event-type-guide-popover` または `.event-type-guide-summary:hover` 親の隣接構造を調整する（**「表示」テキストにマウスオーバーしたとき**に合わせるため、`summary` ホバーでポップアップ表示が望ましい）

**推奨セレクタ例（構造調整後）:**

```css
.event-type-guide-popover {
  /* 非表示 */
}
.event-type-guide-details:hover .event-type-guide-popover,
.event-type-guide-details:focus-within .event-type-guide-popover {
  /* 表示 */
}
```

※ `popover` が `details` の**子**だと、`summary` ホバーで兄弟の `popover` を出すには、**`popover` を `details` 内の `summary` の後に置く**か、**ラッパーで `details` と `popover` を兄弟**にして `summary:hover ~ .popover` を使う。実装時に DOM を微調整すること。

- [ ] **Step 7:** `npm run build` で型・ビルドが通ること

---

## Task 4: アクセシビリティと重複の見直し

**Files:**
- Modify: `frontend/src/panels/events/EventsPanel.tsx`, `App.css`

- [ ] **Step 1:** スクリーンリーダー向けに、ポップアップを常に DOM に重複させると同じ内容が二重に読まれる可能性がある。**`popover` に `aria-hidden={true}`** を付け、インライン `details` 内の本文を**主な**情報源とする（またはその逆を取る）。いずれか一方を `aria-hidden` で隠す。

- [ ] **Step 2:** `prefers-reduced-motion: reduce` がある場合は `transition` を無効化（任意・小さな差分なら省略可）

---

## Task 5: 検証

- [ ] **Step 1:** `cd frontend && npm test -- --run && npm run build`

- [ ] **Step 2:** 手動: イベント一覧でガイドあり行の「表示」にマウスオーバー → ポップアップに意味・原因・対処が表示される

- [ ] **Step 3:** 手動: タブで `summary` にフォーカス → ポップアップまたは `details` 展開で内容にアクセスできる

- [ ] **Step 4:** Conventional Commits でコミット（例: `feat(frontend): show event type guide popover on hover`）

---

## 計画レビュー

可能なら `plan-document-reviewer` でプラン本文をレビュー（実装前）。

---

## 実行の選び方

プラン承認後:

1. **Subagent-Driven（推奨）** — タスクごとにサブエージェント + レビュー  
2. **Inline Execution** — 同一セッションで `executing-plans` に沿って一括実行  

どちらで進めるか指定してください。
