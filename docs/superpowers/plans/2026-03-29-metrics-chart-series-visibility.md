# メトリクスグラフ・系列表示トグル実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: **`@superpowers:subagent-driven-development`**（推奨）または **`@superpowers:executing-plans`**。ステップはチェックボックス（`- [ ]`）で追跡する。
>
> **TDD:** **`@superpowers:test-driven-development`** を厳守する。本計画では **本番コードを書く前に必ず失敗するテストを追加**し、**失敗理由が仕様どおりであることを確認してから**最小実装する。各タスク末尾で **`cd frontend && npm test`** がグリーンであることを確認する。コミットは **タスク単位またはグリーンごと**（頻繁に）行う。

**Goal:** メトリクスパネルの Recharts 折れ線グラフで、**凡例クリック**により各系列の表示／非表示を切り替える。対象は **エンティティ分割メトリクス（`host` モード）の左軸の複数系列**に加え、**イベント件数の右軸系列（`dataKey="evCount"`）**も含む。単一メトリクス（`single` モード）では **`v`** と **`evCount`**（イベント線が有効なとき）が対象。

**Architecture:** Recharts 3 は `Line` の **`hide`** と凡例の **`inactive`** を連動できるが、**凡例クリックの自動トグルはアプリ側実装が必要**とみなす。表示状態は **`hiddenSeriesDataKeys: Set<string>`**（非表示にしたい `dataKey` の集合）として React state で保持し、各 `Line` に `hide={hiddenSeriesDataKeys.has(dataKey)}` を渡す。`Legend` に Recharts の **`onClick`**（[`DefaultLegendContent` の型](../../../frontend/node_modules/recharts/types/component/DefaultLegendContent.d.ts)）を渡し、クリックされた `LegendPayload.dataKey` を文字列化してトグルする。**系列構成が変わったとき**（メトリクスキー変更・ホスト系列一覧の変化・イベント線の表示可否の変化など）は **非表示状態をクリア**して誤った `dataKey` が残らないようにする。ロジックのうち **純関数にできる部分**（トグル・リセット判定・キーの正規化）は **[frontend/src/metrics/metricsChartSeriesVisibility.ts](../../../frontend/src/metrics/metricsChartSeriesVisibility.ts)** に切り出し、**Vitest で単体テスト**する。CSV エクスポートは **生データのまま**（表示トグルと無関係）とし、変更しない。

**Tech Stack:** React 19、TypeScript、Vite、Vitest、Recharts 3.8、既存 [frontend/src/hooks/useMetricsPanelController.ts](../../../frontend/src/hooks/useMetricsPanelController.ts)、[frontend/src/panels/metrics/MetricsPanel.tsx](../../../frontend/src/panels/metrics/MetricsPanel.tsx)。

**関連（先行）:** ブラインストーミング時の方針は [.cursor/plans/グラフ系列表示トグル_b2dcbf12.plan.md](../../../.cursor/plans/グラフ系列表示トグル_b2dcbf12.plan.md) を参照。本ドキュメントが実装手順の正とする。

---

## ブランチ方針

- **ベース:** `main`（最新を `git pull` 済みであること）。
- **ブランチ名例:** `feat/metrics-chart-series-visibility`
- 作業開始時にフィーチャーブランチを切り、以降のコミットは原則そのブランチ上。

---

## ファイル構成

| ファイル | 責務 |
| -------- | ---- |
| [frontend/src/metrics/metricsChartSeriesVisibility.ts](../../../frontend/src/metrics/metricsChartSeriesVisibility.ts)（新規） | 非表示 `dataKey` 集合のトグル、凡例 `dataKey` の正規化、**チャート同一性キー**の算出、同一性変化時のクリア判定など **純関数のみ** |
| [frontend/src/metrics/metricsChartSeriesVisibility.test.ts](../../../frontend/src/metrics/metricsChartSeriesVisibility.test.ts)（新規） | 上記の TDD 用テスト（日本語の `describe` / `it`） |
| [frontend/src/hooks/useMetricsPanelController.ts](../../../frontend/src/hooks/useMetricsPanelController.ts) | `hiddenSeriesDataKeys` の `useState`、凡例 `onLegendClick`、`useEffect` で系列同一性が変わったときに **空の `Set` にリセット**、`MetricsPanel` が `Line` / `Legend` に渡す値を return |
| [frontend/src/panels/metrics/MetricsPanel.tsx](../../../frontend/src/panels/metrics/MetricsPanel.tsx) | 各 `Line` に `hide` を付与、`Legend` に `onClick`、凡例アイテムがクリック可能と分かる **スタイル**（既存 CSS 方針に合わせる） |

**変更しないもの:** [frontend/src/metrics/metricCsv.ts](../../../frontend/src/metrics/metricCsv.ts)（CSV は全データのまま）。

---

## 純関数 API（実装者向けメモ・テストの契約）

以下は **例**。実装時にテストが先に失敗するように、**まずテスト内で期待する関数名・シグネチャを固定**してよい。

```typescript
/** 非表示にしたい dataKey の集合を、1 キー分トグルした新しい Set を返す（入力は破壊しない） */
export function toggleHiddenSeriesDataKey(
  hidden: ReadonlySet<string>,
  dataKey: string,
): Set<string>

/** Recharts 凡例 payload の dataKey を安全に string 化。トグルに使えないときは null */
export function legendDataKeyToString(dataKey: unknown): string | null

/**
 * 系列構成リセット用の安定キー。metricKey + mode + ソート済み series dataKeys + showEventLine 等。
 * 文字列が変われば useEffect で hidden をクリアする。
 */
export function buildMetricsChartSeriesIdentityKey(params: {
  metricKey: string
  chartMode: 'single' | 'host'
  metricSeriesDataKeys: readonly string[]
  showEventLine: boolean
}): string
```

---

### Task 1: 純関数モジュール（TDD）

**Files:**

- Create: [frontend/src/metrics/metricsChartSeriesVisibility.test.ts](../../../frontend/src/metrics/metricsChartSeriesVisibility.test.ts)
- Create: [frontend/src/metrics/metricsChartSeriesVisibility.ts](../../../frontend/src/metrics/metricsChartSeriesVisibility.ts)

- [ ] **Step 1: RED — 失敗するテストを書く（本番ファイルはまだ作らない、または空の export でない関数を import してコンパイルエラーにしてもよいが、Vitest の「失敗」は実行時失敗が望ましい）**

最低限、次の **3 観点**を **別 `it`** で書く（1 テスト 1 挙動）。

1. `toggleHiddenSeriesDataKey`: 空集合から `'a'` をトグル → `Set(['a'])`、もう一度トグル → 空。
2. `legendDataKeyToString`: 文字列はそのまま、数値などは `String` 可能なら文字列化、**`null`/`undefined` は `null`**（仕様をテスト名に書く）。
3. `buildMetricsChartSeriesIdentityKey`: `metricSeriesDataKeys` の順序が違っても **同じ集合なら同じキー**（ソートして正規化する実装を期待）。

```typescript
import { describe, expect, it } from 'vitest'
import {
  toggleHiddenSeriesDataKey,
  legendDataKeyToString,
  buildMetricsChartSeriesIdentityKey,
} from './metricsChartSeriesVisibility'

describe('toggleHiddenSeriesDataKey', () => {
  it('同じ dataKey を二度トグルすると元の非表示集合に戻る', () => {
    const hidden = toggleHiddenSeriesDataKey(new Set(), 'host-1')
    expect([...hidden].sort()).toEqual(['host-1'])
    const hidden2 = toggleHiddenSeriesDataKey(hidden, 'host-1')
    expect([...hidden2]).toEqual([])
  })
})
```

（上記は例。**実装前にファイルを import すると存在しないので、Step 1 ではテストファイルだけ追加し、Step 2 で `npm test` が「モジュールがない」または「関数が未 export」で失敗することを確認する。**）

- [ ] **Step 2: 失敗を確認する**

Run:

```bash
cd frontend && npm test -- src/metrics/metricsChartSeriesVisibility.test.ts
```

Expected: **FAIL**（関数未実装、または export なし）。

- [ ] **Step 3: GREEN — 最小実装**

[frontend/src/metrics/metricsChartSeriesVisibility.ts](frontend/src/metrics/metricsChartSeriesVisibility.ts) に、テストが通る最小コードのみ書く。JSDoc は **export した純関数に日本語で簡潔に**付与する（プロジェクトルール）。

- [ ] **Step 4: グリーンを確認する**

Run:

```bash
cd frontend && npm test -- src/metrics/metricsChartSeriesVisibility.test.ts
```

Expected: **PASS**。

- [ ] **Step 5: リファクタ**（任意）

重複があれば整理する。テストは引き続き PASS。

- [ ] **Step 6: コミット**

```bash
git add frontend/src/metrics/metricsChartSeriesVisibility.ts frontend/src/metrics/metricsChartSeriesVisibility.test.ts
git commit -m "feat(metrics): add series visibility helpers with tests"
```

---

### Task 2: `useMetricsPanelController` に状態とリセットを組み込む

**Files:**

- Modify: [frontend/src/hooks/useMetricsPanelController.ts](../../../frontend/src/hooks/useMetricsPanelController.ts)

**方針:** フックの **副作用は単体テストしない**（既存に `renderHook` パターンがないため）。**純関数は Task 1 で済ませる**。本タスクの完了条件は **型チェック・全フロントテスト・リント**。

- [ ] **Step 1: `seriesIdentityKey` を `useMemo` で算出**

`buildMetricsChartSeriesIdentityKey` に渡す引数は、`chartModel.mode`、`metricKey`、`chartModel.metricSeries.map(s => s.dataKey)`（ソートは関数内でも可）、`showEventLine` から組み立てる。

- [ ] **Step 2: `hiddenSeriesDataKeys` の state と `toggle`**

`useState<Set<string>>(() => new Set())`。`toggle` は `setState` 内で `toggleHiddenSeriesDataKey` を利用。

- [ ] **Step 3: `useEffect` で identity を監視し、変化時に hidden をクリア**

依存配列に `seriesIdentityKey` のみを入れる簡潔さを推奨。

- [ ] **Step 4: 凡例用 `onLegendClick`**

シグネチャは Recharts の `(data, index, event) => void` に合わせ、`data.dataKey` を `legendDataKeyToString` 経由でトグル。`dataKey` が取れない場合は no-op。

- [ ] **Step 5: return に `hiddenSeriesDataKeys`、`onMetricsLegendClick`（名前は実装で統一）を追加**

- [ ] **Step 6: 検証**

Run:

```bash
cd frontend && npm test
```

Expected: 全 PASS。

Run:

```bash
cd frontend && npm run lint
```

Expected: エラーなし。

- [ ] **Step 7: コミット**

```bash
git add frontend/src/hooks/useMetricsPanelController.ts
git commit -m "feat(metrics): track hidden chart series in metrics panel controller"
```

---

### Task 3: `MetricsPanel` の `Line` / `Legend` 結線とスタイル

**Files:**

- Modify: [frontend/src/panels/metrics/MetricsPanel.tsx](../../../frontend/src/panels/metrics/MetricsPanel.tsx)

- [ ] **Step 1: コントローラから `hiddenSeriesDataKeys` と凡例ハンドラを分割代入**

- [ ] **Step 2: 各 `Line` に `hide={hiddenSeriesDataKeys.has(...)}`**

`single` モードの左軸は `dataKey="v"`、`host` モードは `s.dataKey`、イベント線は `'evCount'`。

- [ ] **Step 3: `<Legend ... onClick={...} />`**

コントローラが返すハンドラをそのまま渡す。

- [ ] **Step 4: 凡例クリック可能の UX**

例: `wrapperStyle` に `cursor` を足す、または親にクラスを付け [frontend/src/App.css](../../../frontend/src/App.css) に **メトリクスパネル配下にスコープ**した `.recharts-legend-item { cursor: pointer; }` を追加。**ダークテーマで既存トークンを壊さないこと。**

- [ ] **Step 5: 検証**

Run:

```bash
cd frontend && npm test && cd .. && cd frontend && npm run lint
```

- [ ] **Step 6: 手動確認（チェックリスト）**

  - `host` モード: 複数系列をそれぞれクリックで非表示→再表示。
  - イベント線あり: `evCount` も同様。
  - `single` モード + イベント線: `v` と `evCount` のトグル。
  - メトリクスキー変更後、以前に隠した系列が **誤って残らない**。
  - SVG ダウンロードで、非表示の線が **描画に含まれない**（Recharts の `hide` 挙動に従う）。

- [ ] **Step 7: コミット**

```bash
git add frontend/src/panels/metrics/MetricsPanel.tsx frontend/src/App.css
git commit -m "feat(metrics): wire legend click to line visibility"
```

---

## 計画レビュー（writing-plans 手順）

1. 本ファイルを **`@superpowers:plan-document-reviewer`**（またはプロジェクトの plan-document-reviewer プロンプト）に渡し、レビューする。
2. 指摘があれば本ファイルを修正し、再レビュー（最大 3 回目安）。
3. ✅ 承認後、実装へ進む。

---

## 実行の引き渡し

計画のレビューが通ったら、実装者へ次を提示する。

**Plan complete and saved to [docs/superpowers/plans/2026-03-29-metrics-chart-series-visibility.md](./2026-03-29-metrics-chart-series-visibility.md). Two execution options:**

1. **Subagent-Driven（推奨）** — タスクごとに新しいサブエージェントを起動し、タスク間でレビューする。**REQUIRED SUB-SKILL:** `@superpowers:subagent-driven-development`
2. **Inline Execution** — 同一セッションで `@superpowers:executing-plans` に従いチェックポイント付きで実行する。

**Which approach?**
