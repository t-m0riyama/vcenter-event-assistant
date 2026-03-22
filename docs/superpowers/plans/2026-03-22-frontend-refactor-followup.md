# Frontend Refactor Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既に `panels/` 分割・Zod・`rawItemCount` 等が入った前提で、**バンドルサイズ・重いフックの責務分割・重複パターンの除去**など、投資対効果の高いリファクタを段階的に完了させる。

**Architecture:** 変更は主に `frontend/src` に限定する。ルートは `React.lazy` + `Suspense` でタブ単位（または設定サブタブ単位）を遅延読み込みし、初期 JS を削る。`EventsPanel` は `useEventsPanel`（仮）に一覧取得・CSV・コメント編集の状態と副作用を移し、UI は表示とイベント配線に集中させる。`useMetricsPanelController` は「キー一覧 / 系列取得 / CSV・SVG」などにファイル分割し、単体テスト可能な純粋関数を増やす。共通の「マウント時フェッチ + `onError`」は小さな `useReportedFetch` のようなフックに寄せるか、各パネルでコピペを残すかは YAGNI で判断する（最初はメトリクスとイベントの 2 箇所だけ共通化して十分）。

**Tech Stack:** React 19、Vite 5、TypeScript、Vitest、Playwright、既存の Zod / `toErrorMessage`。

---

## 現状のファイルマップ（この計画で触る可能性が高いもの）

| 領域 | ファイル | 役割・備考 |
|------|----------|------------|
| シェル | `frontend/src/App.tsx` | タブ・エラー表示。lazy の `Suspense` 置き場 |
| エントリ | `frontend/src/main.tsx` | 必要なら `Suspense` の fallback をここに置くか App に置くか決める |
| メトリクス | `frontend/src/hooks/useMetricsPanelController.ts`（~400 行超） | 分割の主対象 |
| メトリクス UI | `frontend/src/panels/metrics/MetricsPanel.tsx` | 表示のみに近づける |
| イベント | `frontend/src/panels/events/EventsPanel.tsx`（~420 行） | フック抽出の主対象 |
| 設定 | `frontend/src/panels/settings/*.tsx` | フェッチ共通化の候補 |
| API 型 | `frontend/src/api/schemas.ts` | 追加 Zod の置き場 |
| テスト | `frontend/src/**/*.test.ts(x)`、`frontend/e2e/*.spec.ts` | リグレッション |

---

## 効果の見込みが高い提案（優先度順）

### A. ルート（タブ）単位のコード分割（バンドル ~666 kB 警告への対応）

**狙い:** 初回ロードで Recharts・重いパネルを読ませない。Lighthouse / 体感の改善。

**方針:** `App.tsx` で `const MetricsPanel = lazy(() => import('./panels/metrics/MetricsPanel').then(m => ({ default: m.MetricsPanel })))` のように **named export に合わせる**。`SummaryPanel` / `EventsPanel` も同様に lazy 化するかは、まず **メトリクスだけ** でも効果大（Recharts がここにぶら下がるため）。

**検証:** `npm run build` で chunk が分割されること。`npm run e2e` でタブ遷移が壊れていないこと。

---

### B. `useEventsPanelController` の抽出（`EventsPanel.tsx` の縮小）

**狙い:** 一覧 `load`、ページング、フィルタ、`downloadCsv`、`saveComment` の依存配列と `useCallback` が 1 ファイルに密集しており、変更時のリグレッションコストが高い。

**方針:** `frontend/src/hooks/useEventsPanelController.ts`（新規）に状態と副作用を移す。`EventsPanel.tsx` は JSX と `useEventsPanelController({ onError })` の戻り値の配線のみ。既存の `normalizeEventListPayload` / `resolveEventApiRange` / `eventCsv` はそのまま利用。

**検証:** `npm run test`、`e2e` のイベント・CSV 関連。必要なら `useEventsPanelController` 向けに **URLSearchParams 構築**だけを `events/buildEventListQuery.ts` の純粋関数に切り出してユニットテストする（TDD しやすい）。

---

### C. `useMetricsPanelController` の責務分割（複数ファイル + 純粋関数）

**狙い:** 418 行のフックは単体テストが困難。系列取得・レート系列・CSV エクスポート・SVG ダウンロードが混在。

**方針（段階的）:**

1. **クエリ組み立て**を `metrics/buildMetricsQueryParams.ts` 等へ（既存パターンがあれば流用）。
2. **CSV / basename** は既に `metricCsv` / `downloadChartSvg` があるので、フック内の「繋ぎ」だけ残す。
3. フックを `useMetricSeriesLoader.ts`（系列 + キー）と `useMetricsPanelController.ts`（オーケストレーション）に分けるか、**最初はファイル 1 つに `metricsPanel/` ディレクトリ**を切って `fetchMetricKeys.ts` / `fetchSeries.ts` を関数として切り出すだけでも可（YAGNI）。

**検証:** 既存の `buildMetricsChartModel.test.ts` 等と合わせて `npm run test`。

---

### D. グローバルエラー表示のインターフェース整理（任意・中優先）

**狙い:** 各パネルが `onError: (e: string | null) => void` を受け取るのは明快だが、タブ切替で `setErr(null)` が散在する。

**方針:** `ErrorBannerContext` を作るか、**現状維持**でもよい。計画としては「**3 ファイル以上で同じパターンが増えたら** Context を検討」と明記し、今回のスコープ外にしてよい（YAGNI）。

---

### E. Zod の残り API（設定パネル PATCH/POST 応答）

**狙い:** `apiGet` の結果は一部 Zod 化済み。POST/PATCH の **レスポンス型**を `schemas.ts` で `safeParse` するとランタイムと型が揃う。

**方針:** 変更範囲が広がるため **独立 PR**。イベント行の PATCH 応答を `eventRowSchema` で parse するなど、小さく始める。

---

## 推奨実施順（1 PR または短い連続ブランチ）

1. **A（lazy）** — 見えやすい成果、リスクは `Suspense` のフォールバック文言だけ注意。
2. **B（Events フック）** — 可読性と今後の機能追加（フィルタ増）に効く。
3. **C（Metrics 分割）** — 触る頻度が高いほど効く。時間がなければ `metricsPanel/` に関数だけ切り出しで止めてよい。
4. **E** — 別計画でも可。

---

## Task 1: メトリクスタブの遅延読み込み

**Files:**

- Modify: `frontend/src/App.tsx`
- Modify: `frontend/e2e/app-flows.spec.ts`（必要なら `waitFor` / `timeout` を微調整）
- Test: 手動で `npm run build` と `npm run e2e`

- [ ] **Step 1: 失敗する前提の確認**

現状: `npm run build` の警告に単一 chunk ~666 kB が出ることをメモする。

- [ ] **Step 2: `lazy` + `Suspense` を App に追加**

```tsx
import { lazy, Suspense, useState } from 'react'

const MetricsPanel = lazy(async () => {
  const m = await import('./panels/metrics/MetricsPanel')
  return { default: m.MetricsPanel }
})

// tab === 'metrics' のとき:
<Suspense fallback={<p className="hint">グラフを読み込み中…</p>}>
  <MetricsPanel onError={setErr} perfBucketSeconds={...} />
</Suspense>
```

- [ ] **Step 3: ビルドで chunk 分割を確認**

Run: `cd frontend && npm run build`

Expected: `dist/assets/` に `MetricsPanel` 系の別 chunk が出る（ファイル名はハッシュ）。

- [ ] **Step 4: E2E**

Run: `cd frontend && npm run e2e`

Expected: 13 tests passed（グラフタブのテストがあれば通過）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "perf(frontend): lazy-load metrics panel to shrink initial bundle"
```

---

## Task 2: `useEventsPanelController` の抽出（骨格）

**Files:**

- Create: `frontend/src/hooks/useEventsPanelController.ts`
- Modify: `frontend/src/panels/events/EventsPanel.tsx`
- Test: 既存 `App.error.test.tsx` + E2E（イベント）

- [ ] **Step 1: フックに状態を丸ごと移す（挙動変更なし）**

`EventsPanel` 内の `useState` / `useCallback` / `useEffect` を新フックへコピーし、コンポーネントは戻り値を受け取るだけにする。

- [ ] **Step 2: `npm run test` と `npm run lint`**

Expected: すべて PASS。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useEventsPanelController.ts frontend/src/panels/events/EventsPanel.tsx
git commit -m "refactor(frontend): extract useEventsPanelController from EventsPanel"
```

---

## Task 3（任意）: イベント一覧クエリの純粋関数 + テスト

**Files:**

- Create: `frontend/src/events/buildEventListQuery.ts`
- Create: `frontend/src/events/buildEventListQuery.test.ts`
- Modify: `frontend/src/hooks/useEventsPanelController.ts`（クエリ組み立てを関数呼び出しに）

- [ ] **Step 1: 失敗するテスト**

`limit` / `offset` / 任意フィルタが `URLSearchParams` に反映されることを検証。

- [ ] **Step 2: 実装**

- [ ] **Step 3: `npx vitest run frontend/src/events/buildEventListQuery.test.ts`**

- [ ] **Step 4: Commit**

---

## Task 4（任意）: `useMetricsPanelController` の関数切り出し

**Files:**

- Create: `frontend/src/metrics/metricsPanel/fetchMetricKeys.ts`（例: 名前は実装時に既存に合わせる）
- Modify: `frontend/src/hooks/useMetricsPanelController.ts`

- [ ] **Step 1: `loadMetricKeys` 相当のロジックを純粋関数または非同期関数に分離**

- [ ] **Step 2: 既存テスト + `npm run test`**

- [ ] **Step 3: Commit**

---

## 計画レビュー（ローカル）

- [ ] このドキュメントを別ブランチで読んだエンジニアが、**A だけ 1 日で終わる**見込みが立つか確認する。
- [ ] `plan-document-reviewer` サブエージェントが利用可能なら、本ファイルと `@writing-plans` に沿ってレビューを 1 回回し、指摘があれば本計画を更新する（最大 3 イテレーション）。

---

## 実行の選び方

**Plan complete and saved to `docs/superpowers/plans/2026-03-22-frontend-refactor-followup.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — タスクごとに新しいサブエージェントを起動し、タスク間でレビューする。推奨スキル: `superpowers:subagent-driven-development`。

**2. Inline Execution** — このセッションで `superpowers:executing-plans` に従い、チェックポイントごとにまとめて実装する。

**Which approach?**
