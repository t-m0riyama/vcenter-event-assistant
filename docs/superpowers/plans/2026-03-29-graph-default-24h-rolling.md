# グラフタブのデフォルト表示期間（直近24時間）とローリング窓 Implementation Plan

> **For agentic workers:** 本プランは **superpowers:subagent-driven-development**（同一セッション内・タスク単位）と **superpowers:test-driven-development**（実装サブエージェントが各タスクで RED→GREEN）を組み合わせて実行する。チェックボックス（`- [ ]`）で進捗を追う。

**Goal:** グラフタブを開いた直後から、表示期間が **直近24時間**（表示タイムゾーン上の壁時計で「いま」を終端とした相対窓）になる。クイックの「過去24時間」「過去 N 日」と同様の **相対長さ** を内部に保持し、**自動更新が有効なとき**はその長さごとに窓を再計算して終端が現在に追従する。ユーザーが日付・時刻を手動で変えたあとは **手動モード** とし、表示期間は固定のまま再取得のみとする。

**要件出典:** brainstorming で合意（初期は24時間、B に近いローリング、手動変更後はユーザー指定を優先、クイックの各相対窓も自動更新で追従、手動で両方空にした場合は従来どおり期間フィルタなし）。

**Tech Stack:** TypeScript、React、`frontend` の Vitest／Playwright。既存の `presetRelativeRangeWallParts`（`zonedRangeParts.ts`）と `resolveMetricsGraphRange`（`graphRange.ts`）を利用する。

---

## 現状（実装前のベースライン）

- `useMetricsPanelController` の `rangeParts` 初期値は **空**（`EMPTY_ZONED_RANGE_PARTS`）。メトリクス API は `limit=500` で期間なし取得に近い挙動。
- `ZonedRangeFields` のクイックは `presetRelativeRangeWallParts(durationMs, timeZone)` を `onChange` に渡すだけで、**ローリング／手動の区別がない**。
- 自動更新は `MetricsPanel` で `invalidateSeriesCache` + `load`。**窓は動かない**。
- 自動更新 ON/OFF は「設定 → 一般」のみの想定だったが、**表示期間セクション内にチェックを置く**要望あり（別途 UI タスクとして本プランに含める）。

---

## 目標ふるまい（仕様）

1. **初期表示:** `rolling` モード、`rollingDurationMs = 24h`。`rangeParts` は `presetRelativeRangeWallParts(METRICS_DEFAULT_ROLLING_DURATION_MS, timeZone)` で初期化する。
2. **クイックプリセット（過去24時間／2日／7日／30日）:** `rolling` に戻し、対応する `rollingDurationMs` を保存。表示は従来どおり相対窓。
3. **手動編集:** `ZonedRangeFields` の日付・時刻のいずれかをユーザーが変更したら `**manual`**。以降の自動更新は **窓を変えず** `load` のみ（現状と同様）。
4. **自動更新（インターバル）:**
  - `rolling`: 毎回 `presetRelativeRangeWallParts(rollingDurationMs, timeZone)` で `rangeParts` を更新し、**既存の `vcenterId` / `metricKey` / `rangeParts` 依存の `useEffect`** によりシリーズ取得が走る（**二重リクエストにならないよう**、`setRangeParts` のみにし `load` を二重に呼ばない）。
  - `manual`: `invalidateSeriesCache` + `load(..., { silent: true })` のみ。
5. **表示タイムゾーン変更:** `rolling` のときだけ、`rollingDurationMs` を保ったまま `presetRelativeRangeWallParts` で窓を再計算。`manual` はユーザー入力をそのまま（既存フィールド値を維持）。
6. **手動で開始・終了を両方空:** 既存どおり `resolveMetricsGraphRange` は **期間なし**（`limit=500` 系）。`manual` でのみ発生しうる。
7. **「再取得」ボタン:** `rolling` のときは窓を **現在に合わせて** から取得（自動更新と同じく相対窓の再計算 + effect で取得）。`manual` は従来どおり `load` のみ。

---

## 状態モデル（フロント）


| 状態                     | 型                      | 説明                               |
| ---------------------- | ---------------------- | -------------------------------- |
| `graphRangeFollowMode` | `'rolling' | 'manual'` | クイック追従か手入力固定か。                   |
| `rollingDurationMs`    | `number`               | `rolling` 時の相対長さ（ミリ秒）。クイック選択と同期。 |
| `rangeParts`           | `ZonedRangeParts`      | 入力欄・API 解決の唯一のソース。               |


**定数:** `METRICS_DEFAULT_ROLLING_DURATION_MS = 86400000` を `zonedRangeParts.ts` に export（グラフ初期・文言と共有）。

---

## ファイル構成（変更）


| ファイル                                                  | 役割                                                                                                                                                                                                                        |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/datetime/zonedRangeParts.ts`            | `METRICS_DEFAULT_ROLLING_DURATION_MS` の export（JSDoc 付与）。                                                                                                                                                                 |
| `frontend/src/datetime/ZonedRangeFields.tsx`          | 任意 prop `onQuickPreset?: (durationMs: number) => void`。指定時はクイックボタンがこれを呼び、**指定なし**のときは従来どおり `onChange(presetRelativeRangeWallParts(...))`（イベントタブ互換）。                                                                       |
| `frontend/src/hooks/useMetricsPanelController.ts`     | 上記状態・`onGraphRangeFieldsChange`・`applyRollingPreset`・タイムゾーン変更 effect・`runMetricsAutoRefresh`・`reloadMetricsSeries`。`setRangeParts` は hook 内部のみ。                                                                           |
| `frontend/src/panels/metrics/MetricsPanel.tsx`        | `ZonedRangeFields` に `onChange={onGraphRangeFieldsChange}` と `onQuickPreset={applyRollingPreset}`。自動更新は `runMetricsAutoRefresh`。再取得ボタンは `reloadMetricsSeries`。表示期間内の自動更新チェック（既存案）を維持するなら `useAutoRefreshPreferences` と連携。 |
| `frontend/src/panels/events/EventsPanel.tsx`          | `ZonedRangeFields` は `**onQuickPreset` なし**のまま（挙動変更なし）。                                                                                                                                                                   |
| `frontend/e2e/app-validation-and-integration.spec.ts` | グラフの「片側だけ入力」テスト: デフォルトで両端が埋まるため、**終了側を空にする**など明示的に片側のみの状態を作ってからバナー期待を検証。                                                                                                                                                  |


**スコープ外:** バックエンド API の既定値変更、概要／イベントタブのデフォルト期間、ローリング専用の別 UI（「直近24時間（自動）」ラベルのみ表示など）は行わない（必要なら別プラン）。

---

## テスト方針

- **単体:** `useMetricsPanelController` または `zonedRangeParts` 周辺で、`rolling` 初期化・`applyRollingPreset` で `rollingDurationMs` が変わること・手動 `onGraphRangeFieldsChange` で `manual` になること（モック時刻／`vi.spyOn(Date, 'now')` は任意）。
- **回帰:** `ZonedRangeFields` の既存利用（イベント）でクイックが従来どおり動くこと。
- **E2E:** 上記バリデーションシナリオの更新。スクリーンショット系はグラフに `from`/`to` が付くため API 応答は従来通りでよい場合が多いが、失敗時はクエリパラメータを確認。

---

## Subagent-Driven Development（実行オーケストレーション）

スキル: [subagent-driven-development](file:///Users/moriyama/.cursor/plugins/cache/cursor-public/superpowers/8ea39819eed74fe2a0338e71789f06b30e953041/skills/subagent-driven-development/SKILL.md)。リポジトリ内に `implementer-prompt.md` は無いため、**オーケストレーターが下記「タスクごとの依頼文」をそのまま（または要約せずに）実装サブエージェントへ渡す**。

### ルール

- **タスクは直列:** 実装サブエージェントを複数並列に起動しない（コンフリクト防止）。Task 1→2→3→4 の順。
- **各タスクのゲート（順序固定）:** ① 実装サブエージェント（TDD: 失敗テスト→最小実装→テスト緑）→ ② **仕様適合レビュー**（本ドキュメントの「目標ふるまい」「ファイル構成」と照合）→ ③ **コード品質レビュー**。仕様レビューが ✅ になるまで品質レビューに進まない。
- **コンテキストの渡し方:** サブエージェントにセッション履歴を継承させない。**このファイルから該当 Task の全文、触るファイルパス、完了条件**を貼る。プラン本体を「読んで」とだけ指示してファイル探索させない。
- **ステータス handling:** 実装サブエージェントが `NEEDS_CONTEXT` / `BLOCKED` を返したら、人間またはオーケストレーターが不足情報を補足して再ディスパッチ。`DONE_WITH_CONCERNS` は懸念を読んでからレビューへ。
- **ブランチ:** 着手前に **superpowers:using-git-worktrees**（またはチーム規約の作業ブランチ）で隔離。全タスク完了後は **superpowers:finishing-a-development-branch** でマージ方針を決める。
- **関連スキル:** 実装者は **test-driven-development** を必須とする。レビュー依頼の型は **requesting-code-review** を流用可。

### タスクごとの依頼文テンプレート（貼り付け用）

各 Task の節（「### Task N: …」以下の Step 一覧）を**そのままコピー**し、先頭に次を付ける:

```text
あなたは実装担当サブエージェントです。以下は vcenter-event-assistant のグラフタブ表示期間プランの Task のみです。
- TDD: 本番コードの前に失敗テストを書き、npm test で RED を確認してから GREEN。
- 完了したら: 変更ファイル・テスト結果・conventional commit 案・自己レビュー1行を報告。ステータス DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED のいずれか。

---（ここに ### Task N: から次の --- までを貼る）---
```

### レビュー依頼文テンプレート

**仕様レビューアー向け:**

```text
仕様適合レビュー。根拠は docs/superpowers/plans/2026-03-29-graph-default-24h-rolling.md の「目標ふるまい」「該当 Task」。差分の意図と照合し、過不足・仕様外を列挙。✅/❌。
```

**品質レビューアー向け:**

```text
コード品質レビュー。型安全性、命名、重複、エッジケース、テストの意図。仕様は既に ✅。改善必須/任意を分ける。
```

全 Task 完了後、**最終レビュー**（全体整合）を 1 回挟み、から **finishing-a-development-branch**。

---

## 実装タスク

### Task 1: 定数と `ZonedRangeFields` の拡張

- **Step 1:** `METRICS_DEFAULT_ROLLING_DURATION_MS` を `zonedRangeParts.ts` に追加し export。
- **Step 2:** `ZonedRangeFields` に `onQuickPreset?: (durationMs: number) => void` を追加。クイックボタンは `onQuickPreset?.(ms) ?? onChange(presetRelativeRangeWallParts(ms, timeZone))` のイメージで分岐（イベントパネルは後者のみ）。
- **Step 3:** `npm test`（関連テストのみ可）

---

### Task 2: `useMetricsPanelController` のローリング／手動と副作用

- **Step 1:** `graphRangeFollowMode` / `rollingDurationMs` / 初期 `rangeParts`（`presetRelativeRangeWallParts(METRICS_DEFAULT_ROLLING_DURATION_MS, timeZone)`）を導入。
- **Step 2:** `onGraphRangeFieldsChange`（常に `manual` + `setRangeParts`）、`applyRollingPreset`（`rolling` + `rollingDurationMs` + `setRangeParts`）。
- **Step 3:** 表示 TZ 変更時の effect（`prevTimeZoneRef` 等で初回スキップ）。`rolling` のときのみ窓再計算 + 必要なら `lastSeriesFetchRef` 無効化。
- **Step 4:** `runMetricsAutoRefresh`：`invalidateSeriesCache` 後、`rolling` なら `setRangeParts(preset...)` のみ、`manual` なら `load(metricKey, { silent: true })`。
- **Step 5:** `reloadMetricsSeries`：再取得ボタン用。`rolling` なら窓更新のみ + effect に任せる、`manual` なら `load(metricKey)`。
- **Step 6:** return から `setRangeParts` を外し、上記ハンドラと `runMetricsAutoRefresh` / `reloadMetricsSeries` を公開。
- **Step 7:** 既存の `rangeParts` 変更トリガの `useEffect`（シリーズ取得）と二重取得が起きないことをコードレビューで確認。

---

### Task 3: `MetricsPanel` の配線

- **Step 1:** `MetricsPanel` で `onGraphRangeFieldsChange` / `applyRollingPreset` / `runMetricsAutoRefresh` / `reloadMetricsSeries` を受け取り、`useIntervalWhenEnabled` のコールバックを `runMetricsAutoRefresh` に差し替え。
- **Step 2:** `ZonedRangeFields` に `onQuickPreset={applyRollingPreset}` を渡す。
- **Step 3:** 「再取得」ボタンの `onClick` を `reloadMetricsSeries` と `setChartResetKey` の組み合わせに更新（既存の chart リセット要件を維持）。
- **Step 4:** 表示期間内の自動更新チェック（要望どおり）が未実装なら本タスクで追加済みか確認。

---

### Task 4: E2E とドキュメント

- **Step 1:** `app-validation-and-integration.spec.ts` のグラフ・片側入力ケースを、デフォルト24時間下でもエラーバナーが出る操作手順に修正。
- **Step 2:** 必要なら README またはツールチップ1行で「グラフの初期表示は直近24時間」と記載（ユーザー指示がある場合のみ）。

---

## リスク・注意

- `**useState` 初期化と `timeZone`:** 初回レンダーで `useTimeZone()` の値が使えることを前提に `presetRelativeRangeWallParts` で初期化する。SSR なしの SPA 前提で問題にならないかだけ確認。
- **同一 `rangeKey` での自動更新:** 同一分内に二重インターバルが走ると窓が変わらず effect がスキップされる可能性。許容または `invalidateSeriesCache` の扱いをタスク2で確認。
- **作業ブランチに未完了のコントローラ変更だけがある場合:** `MetricsPanel` がまだ `setRangeParts` を参照しているとビルドが壊れるため、**Task 2 と Task 3 を同一 PR／連続コミット**で揃える。

---

## 完了条件

- グラフタブ初回表示で API に `from` / `to`（直近24時間相当）が付く、または同等の範囲指定が行われる。
- クイックで日数を変えたあと、自動更新 ON で窓が現在に追従する（`rolling`）。
- 手動で期間を変えたあとは窓が固定される（`manual`）。
- イベントタブの表示期間 UI の挙動が変わらない。
- CI でフロントの単体／E2E（該当スペック）が通る。

