# ダイジェスト一覧「開始日付のみ」実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. **実装手法は superpowers:test-driven-development に従う**（本書「TDD 方針」）。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ダイジェスト一覧の各行を、従来の「種別 + 開始日時 〜 終了日時」から「**種別 + 開始の暦日のみ**」に変更する。

**表示の例（要件の固定）**

- **従来（参考）:** `daily` と同じ行に `2026/03/28 0:00 〜 2026/03/29 0:00` のようなレンジ（実装では `formatRange` + `omitSeconds` によりロケール依存）。
- **変更後:** `daily` と同じ行に **`2026/03/28` のような開始日付のみ**（時刻なし）。**`〜` も終了日付・時刻も一覧では表示しない。**

**Architecture:** `period_start` を表示タイムゾーンで暦日だけに整形する `formatIsoDateOnlyInTimeZone` を [`formatIsoInTimeZone.ts`](../../frontend/src/datetime/formatIsoInTimeZone.ts) に追加する（`parseApiUtcInstantMs` と `Intl.DateTimeFormat` の `dateStyle: 'short'` のみ）。一覧は [`DigestsPanel.tsx`](../../frontend/src/panels/digests/DigestsPanel.tsx) で `digests-row-range` を復活させ、`formatIsoDateOnlyInTimeZone(period_start, timeZone)` のみを表示。詳細パネルの `formatRange`（開始〜終了・日時）は**変更しない**。

**Tech Stack:** React、TypeScript、Vitest、既存 `useTimeZone`。

**注意:** 日付の見え方は `Intl` とロケールで変わるため、テストでは **ハードコード文字列 `2026/03/28` に依存せず**、同じヘルパーで期待値を組み立てる。

---

## TDD 方針（superpowers:test-driven-development 厳守）

- **アイアン・ロー:** 本番コード（仕様を満たす実装）を、**それを落とすテストを先に書き、失敗をコマンドで見てから**追加する。テスト後付けや「実装に合わせたテスト」は禁止。
- **1 振る舞いあたりのサイクル:**
  1. **RED:** 最小のテストを 1 本追加する（`it` の名前で意図が読めること）。
  2. **Verify RED:** `npm test -- <該当ファイル>` を実行し、**アサーション失敗**であることを確認する（すでに PASS ならテストが無意味なのでやり直す）。
  3. **GREEN:** 本番コードを **テストを通す最小限** で書く。
  4. **Verify GREEN:** 同コマンドで PASS。他テストで回帰がないか確認。
  5. **REFACTOR:** テストを緑のまま重複削除・命名のみ。挙動は増やさない。
- **Task 1:** `formatIsoDateOnlyInTimeZone` は **テストファイルのみ先** → Verify RED → 本番 export + 実装 → Verify GREEN。
- **Task 2:** **`DigestsPanel.test.tsx` のみ先**（この時点では `DigestsPanel.tsx` / `App.css` は触らない）→ Verify RED → 本番の最小変更 → Verify GREEN。
- **赤旗:** テストが最初からパスしたら、テストが要件を表していないか見直す（テストアフターになっている）。

---

## 変更するファイル

| 責務 |
|------|
| [`frontend/src/datetime/formatIsoInTimeZone.ts`](../../frontend/src/datetime/formatIsoInTimeZone.ts) — `formatIsoDateOnlyInTimeZone` 追加（JSDoc は日本語） |
| [`frontend/src/datetime/formatIsoInTimeZone.test.ts`](../../frontend/src/datetime/formatIsoInTimeZone.test.ts) — 日付のみ・無効時 `—`・時刻パターン不在 |
| [`frontend/src/panels/digests/DigestsPanel.tsx`](../../frontend/src/panels/digests/DigestsPanel.tsx) — 一覧に `digests-row-range` と開始日のみ |
| [`frontend/src/panels/digests/DigestsPanel.test.tsx`](../../frontend/src/panels/digests/DigestsPanel.test.tsx) — 一覧に期待日付あり、`〜` や従来レンジ・開始の「時刻付き」表記は一覧に無いこと |
| [`frontend/src/App.css`](../../frontend/src/App.css) — `.digests-row-range` 復帰（`digests-row-kind` と `digests-row-status` の間） |

---

### Task 1: `formatIsoDateOnlyInTimeZone`（TDD）

- [ ] **RED:** [`formatIsoInTimeZone.test.ts`](../../frontend/src/datetime/formatIsoInTimeZone.test.ts) にのみ `formatIsoDateOnlyInTimeZone` 用の `describe` / `it` を追加。[`formatIsoInTimeZone.ts`](../../frontend/src/datetime/formatIsoInTimeZone.ts) には **まだ export しない**（`vitest` が型／import エラーで落ちるのは可。意図は「未実装のため要件を満たさない」状態）。
  - `Asia/Tokyo` で暦年を含む。
  - `\d{1,2}:\d{2}` のような時刻表記を含まない。
  - 無効入力は `'—'`。
- [ ] **Verify RED:** `cd frontend && npm test -- src/datetime/formatIsoInTimeZone.test.ts` で **失敗**を確認（失敗理由が「未実装・未定義」系であること）。
- [ ] **GREEN:** `formatIsoDateOnlyInTimeZone` を本実装で export（JSDoc は日本語）。
- [ ] **Verify GREEN:** 同コマンドで **PASS**。
- [ ] **REFACTOR（任意）:** 重複・名前の整理。テストは緑のまま。
- [ ] **コミット**（ブランチは [`.cursor/rules/git-branch-worktree-before-changes.mdc`](../../.cursor/rules/git-branch-worktree-before-changes.mdc) に従う）。

---

### Task 2: 一覧 UI と結合テスト（TDD）

- [ ] **RED:** **`DigestsPanel.tsx` と `App.css` はまだ変更しない。** [`DigestsPanel.test.tsx`](../../frontend/src/panels/digests/DigestsPanel.test.tsx) のみ更新。`Asia/Tokyo` 固定の既存パターンに合わせ、一覧ナビ内に  
  `formatIsoDateOnlyInTimeZone(periodStart, 'Asia/Tokyo')` と一致するテキストがあること。  
  一覧内に `〜` が無いこと、従来の  
  `` `${formatIsoInTimeZone(periodStart,...)} 〜 ${formatIsoInTimeZone(periodEnd,...)}` ``  
  が無いこと、開始の「時刻付き」単独ラベルが一覧に無いことを検証（既存の「期間は表示しない」系 `it` は本要件に合わせて置換または削除）。
- [ ] **Verify RED:** `cd frontend && npm test -- src/panels/digests/DigestsPanel.test.tsx` で **失敗**を確認。
- [ ] **GREEN:** `DigestsPanel.tsx` に `formatIsoDateOnlyInTimeZone` を import。`useCallback` で一覧用フォーマッタを定義し、`digests-row-kind` の直後に  
  `<span className="digests-row-range">{...}</span>`（**`period_start` の日付のみ**）。`App.css` に `.digests-row-range` を復帰。
- [ ] **Verify GREEN:** 同じ `npm test -- src/panels/digests/DigestsPanel.test.tsx` で PASS。
- [ ] **回帰:** `npm test` 全件と該当ファイルの eslint。
- [ ] **REFACTOR（任意）:** 緑のまま整理。
- [ ] **コミット**。

---

## 検証コマンド

```bash
cd frontend
npm test -- src/datetime/formatIsoInTimeZone.test.ts
npm test -- src/panels/digests/DigestsPanel.test.tsx
npm test
npm run lint -- --max-warnings 0 src/datetime/formatIsoInTimeZone.ts src/panels/digests/DigestsPanel.tsx
```

---

## スコープ外

- 詳細パネルの `digests-detail-meta` の `formatRange`。
- API・DB・`digest.md.j2`・ダウンロードファイル名。

---

## 実行の引き渡し

計画確定後、**Subagent-Driven** と **インライン実行**のどちらで進めるか作業者に確認する。
