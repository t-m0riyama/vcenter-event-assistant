# イベント時刻のタイムゾーン表示 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** ダッシュボード・イベント一覧・メトリクスチャートで、ユーザーが選んだ IANA タイムゾーンで日時を表示し、初回はブラウザのタイムゾーンをデフォルトにする。

**Architecture:** API は現状どおり UTC 想定の ISO8601 文字列を返す。フロントエンドで `Intl.DateTimeFormat` の `timeZone` オプションを使い、同一の表示用関数でテーブルとチャート軸を揃える。選択値は `localStorage` に保存し、次回訪問時に復元する。ブラウザ既定は `Intl.DateTimeFormat().resolvedOptions().timeZone` で取得する。

**Tech Stack:** React 19、Vite 5、TypeScript。新規に Vitest をフロント用に追加して純関数を TDD する。バックエンド変更は不要（YAGNI）。

**補足:** 作業用に brainstorming / using-git-worktrees で専用 worktree を切ると安全（任意）。

---

### Task 1: 日時フォーマット純関数と Vitest

**Files:**

- Create: `frontend/src/datetime/formatIsoInTimeZone.ts`
- Create: `frontend/src/datetime/formatIsoInTimeZone.test.ts`
- Modify: `frontend/package.json`（`test` スクリプト、`vitest` 依存）

**Step 1: Write the failing test**

`frontend/src/datetime/formatIsoInTimeZone.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'
import { formatIsoInTimeZone } from './formatIsoInTimeZone'

describe('formatIsoInTimeZone', () => {
  it('formats UTC instant in Asia/Tokyo', () => {
    const s = formatIsoInTimeZone('2025-06-15T03:00:00.000Z', 'Asia/Tokyo')
    expect(s).toMatch(/2025/)
    expect(s).toMatch(/12:00/)
  })
})
```

`frontend/src/datetime/formatIsoInTimeZone.ts` は空または `throw new Error('todo')` でよい。

**Step 2: Run test to verify it fails**

Run:

```bash
cd frontend && npm install -D vitest && npx vitest run src/datetime/formatIsoInTimeZone.test.ts
```

Expected: FAIL（未実装または import エラー）

**Step 3: Write minimal implementation**

`formatIsoInTimeZone(isoString: string, timeZone: string, locale?: string): string`

- `const d = new Date(isoString)` でパース。`Number.isNaN(d.getTime())` なら `'—'` などフォールバック（仕様をテストに1件追加してもよい）。
- `new Intl.DateTimeFormat(locale ?? undefined, { dateStyle: 'short', timeStyle: 'medium', timeZone }).format(d)` を返す（`locale` は省略時は実行環境のロケール）。

**Step 4: Run test to verify it passes**

Run: 上と同じ `vitest run`

Expected: PASS

**Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/datetime/
git commit -m "feat: add formatIsoInTimeZone with vitest"
```

---

### Task 2: タイムゾーンの既定・永続化・検証ヘルパ

**Files:**

- Create: `frontend/src/datetime/timeZoneStorage.ts`
- Create: `frontend/src/datetime/timeZoneStorage.test.ts`
- Create: `frontend/src/datetime/listTimeZones.ts`（オプション: `Intl.supportedValuesOf` が無い環境向けに短いフォールバック配列）

**Step 1: Write the failing test**

`getDefaultBrowserTimeZone()` が `Intl.DateTimeFormat().resolvedOptions().timeZone` と同じ文字列を返すことをモックなしで検証（Node の Vitest は通常 `UTC`）。

`readStoredTimeZone()` / `writeStoredTimeZone()` は `localStorage` をモックするか、`happy-dom` / `jsdom` を追加して読み書きを検証。

Storage キー例: `vea.displayTimeZone`

**Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/datetime/timeZoneStorage.test.ts
```

**Step 3: Write minimal implementation**

- `getDefaultBrowserTimeZone(): string`
- `readStoredTimeZone(): string | null`
- `writeStoredTimeZone(tz: string): void`
- `isValidIanaTimeZone(tz: string): boolean` — `try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); return true } catch { return false }`

**Step 4: Run test to verify it passes**

**Step 5: Commit**

```bash
git add frontend/src/datetime/timeZoneStorage.ts frontend/src/datetime/timeZoneStorage.test.ts
git commit -m "feat: browser default and persisted timezone helpers"
```

---

### Task 3: React Context でアプリ全体に timeZone を供給

**Files:**

- Create: `frontend/src/datetime/TimeZoneContext.tsx`
- Modify: `frontend/src/App.tsx`（Provider でラップ、ヘッダーにゾーン選択 UI を追加）

**Step 1: Write the failing test（任意・最小）**

Context 自体は結合テストが重いので、Task 1–2 の純関数テストで十分とし、ここでは手動確認に回す。必須にするなら `@testing-library/react` を追加して `useTimeZone` のラッパーコンポーネントで表示文字列を assert。

**Step 2–4: 実装**

- `TimeZoneProvider` の `useEffect` で初回マウント時: `readStoredTimeZone()` が有効ならそれを state、なければ `getDefaultBrowserTimeZone()` を state にし、`writeStoredTimeZone` で保存。
- `value`: `{ timeZone, setTimeZone }` — `setTimeZone` 内で `isValidIanaTimeZone` を通したものだけ保存。

**UI（ヘッダー）:**

- `<select>` の options: `Intl.supportedValuesOf('timeZone')` が使える場合はソート済み一覧。使えない場合は `listTimeZones.ts` の代表的ゾーン + 現在値がリストに無ければ `<option value={current}>` を追加。
- ラベル例: 「表示タイムゾーン」

**Step 5: Commit**

```bash
git add frontend/src/datetime/TimeZoneContext.tsx frontend/src/App.tsx
git commit -m "feat: timezone context and header selector"
```

---

### Task 4: 各パネルで ISO 文字列をフォーマット表示に置き換え

**Files:**

- Modify: `frontend/src/App.tsx`（`SummaryPanel`, `EventsPanel`, `MetricsPanel`）

**対象箇所（現状）:**

- `SummaryPanel`: `h.sampled_at`、`e.occurred_at` をそのまま表示 → `formatIsoInTimeZone(..., timeZone)` に変更。
- `EventsPanel`: `e.occurred_at` 同上。
- `MetricsPanel`: `chartData` の `t: new Date(p.sampled_at).toLocaleString()` → `formatIsoInTimeZone(p.sampled_at, timeZone)` に統一（チャート軸が選択ゾーンと一致）。

各 Panel で `useTimeZone()` を呼ぶ。

**Step 1–4: 実装後の確認**

Run:

```bash
cd frontend && npm run build
```

Expected: 型チェックとビルド成功。

**Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: apply selected timezone to event and metric timestamps"
```

---

### Task 5: 手動検証とリント

**手動:**

1. ヘッダーでタイムゾーンを変更し、サマリー・イベント・メトリクスの時刻表示が一貫して変わること。
2. ページリロード後、選択が `localStorage` から復元されること。
3. プライベートブラウズ初回: ブラウザのタイムゾーン（`Intl`）が初期値になること。

Run:

```bash
cd frontend && npm run lint
```

**Commit（lint 修正のみの場合）:**

```bash
git add frontend/
git commit -m "chore: lint fixes for timezone feature"
```

---

## 参照スキル

- 実装実行: `@superpowers:executing-plans`
- 同一セッションでタスク分割実行: `@superpowers:subagent-driven-development`
- 完了前検証: `@superpowers:verification-before-completion`

---

## テストコマンド一覧

| 目的           | コマンド |
|----------------|----------|
| 単体（日時）   | `cd frontend && npx vitest run` |
| フロントビルド | `cd frontend && npm run build` |
| リント         | `cd frontend && npm run lint` |
| バックエンド（回帰） | ルートで既存の `pytest` があれば `uv run pytest` |
