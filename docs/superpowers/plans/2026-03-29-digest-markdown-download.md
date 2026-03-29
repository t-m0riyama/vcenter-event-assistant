# ダイジェスト詳細 Markdown ダウンロード Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: **`@superpowers:subagent-driven-development`**（推奨）または **`@superpowers:executing-plans`**。ステップはチェックボックス（`- [ ]`）で追跡する。
>
> **TDD:** **`@superpowers:test-driven-development`** を厳守する。各タスクで **失敗するテストを先に書く → 実行して RED を確認 → 最小実装 → GREEN を確認 → リファクタ（テストは緑のまま）**。本機能は新規コードが中心のため、**本番コードをテストより先に書かない**。

**Goal:** ダイジェスト詳細パネルから、**画面上の Markdown 表示と同一の文字列**を UTF-8 の `.md` ファイルとしてブラウザにダウンロードさせる。

**Architecture:** 本文は既存の表示ロジック（`llm_model` に応じた `stripLlmDigestSection`、`repairPipeTablesForGfm`）と **完全一致**させるため、同じ変換を行う純関数を **`DigestsPanel.tsx` から切り出し**、表示とダウンロードの両方から import する。ファイル保存は [`downloadJsonFile`](../../frontend/src/utils/downloadJsonFile.ts) と同様に **`Blob` + 一時 `<a download>`** で行う（新規 API は不要。一覧 `GET /api/digests` のレスポンスに含まれる `DigestRead` だけで足りる）。

**Tech Stack:** React 19、TypeScript、Vite、Vitest、Testing Library（`happy-dom`）、既存 Zod スキーマ `DigestRead`。

**前提（スコープ）:** 形式は **Markdown のみ**。PDF・複数件 ZIP・サーバー側エクスポート API は行わない。ダウンロード本文は **`body_markdown` の生データではなく、画面と同じ加工後**（ユーザー確認済み）。

**関連既存:** [`DigestsPanel.tsx`](../../frontend/src/panels/digests/DigestsPanel.tsx)（17–20 行の `displayMarkdownForDigest`）、[`stripLlmDigestSection.ts`](../../frontend/src/panels/digests/stripLlmDigestSection.ts)、[`repairPipeTablesForGfm.ts`](../../frontend/src/panels/digests/repairPipeTablesForGfm.ts)。

---

## ファイル構成

| ファイル | 責務 |
| -------- | ---- |
| [`frontend/src/panels/digests/getDigestBodyMarkdownForDisplay.ts`](../../frontend/src/panels/digests/getDigestBodyMarkdownForDisplay.ts) | **新規。** `DigestRead` から画面／ダウンロード共通の Markdown 文字列を返す純関数（現 `displayMarkdownForDigest` と同等）。 |
| [`frontend/src/panels/digests/getDigestBodyMarkdownForDisplay.test.ts`](../../frontend/src/panels/digests/getDigestBodyMarkdownForDisplay.test.ts) | **新規。** 上記の挙動テスト（LLM あり／なし、表修復が効くケースは既存パターンに合わせ最小限）。 |
| [`frontend/src/panels/digests/buildDigestDownloadFilename.ts`](../../frontend/src/panels/digests/buildDigestDownloadFilename.ts) | **新規。** `DigestRead` から ASCII 安全な `.md` ファイル名を生成。 |
| [`frontend/src/panels/digests/buildDigestDownloadFilename.test.ts`](../../frontend/src/panels/digests/buildDigestDownloadFilename.test.ts) | **新規。** ファイル名の安定性・サニタイズ。 |
| [`frontend/src/utils/downloadTextFile.ts`](../../frontend/src/utils/downloadTextFile.ts) | **新規。** 任意の文字列を UTF-8 テキストファイルとしてダウンロード（`Blob` + `URL.createObjectURL` + `revokeObjectURL`）。 |
| [`frontend/src/utils/downloadTextFile.test.ts`](../../frontend/src/utils/downloadTextFile.test.ts) | **新規。** トリガーと Blob 内容（または `createObjectURL` に渡された Blob）の検証。 |
| [`frontend/src/panels/digests/DigestsPanel.tsx`](../../frontend/src/panels/digests/DigestsPanel.tsx) | **変更。** 内部関数削除 → `getDigestBodyMarkdownForDisplay` を使用。詳細エリアに「Markdown をダウンロード」ボタンを追加。 |
| [`frontend/src/panels/digests/DigestsPanel.test.tsx`](../../frontend/src/panels/digests/DigestsPanel.test.tsx) | **変更。** ボタン表示・クリック時のダウンロード経路（`URL.createObjectURL` 等の spy）。 |
| [`frontend/src/App.css`](../../frontend/src/App.css) | **任意。** ボタン配置用の最小クラス（既存 `.btn` を流用できるなら空変更でも可）。 |

**変更しないもの:** Python API、DB、`DigestRead` スキーマ。

---

## ブランチ方針

- **ベース:** `main`（最新を `git pull` 済み）。
- **ブランチ名例:** `feat/digest-markdown-download`

---

### Task 1: `buildDigestDownloadFilename` — TDD

**Files:**

- Create: [`frontend/src/panels/digests/buildDigestDownloadFilename.ts`](../../frontend/src/panels/digests/buildDigestDownloadFilename.ts)
- Create: [`frontend/src/panels/digests/buildDigestDownloadFilename.test.ts`](../../frontend/src/panels/digests/buildDigestDownloadFilename.test.ts)

**契約（テストで固定する）:**

- 返り値は **`*.md`** で終わる。
- `id` と `kind` が識別できる（例: `digest-` プレフィックス + 数値 id）。
- `kind` にファイルシステム向けで危険な文字（`/`, `\`, `:`, 空白 等）が含まれる場合は **`_` 等に置換**し、連続する区切りは潰すなど **ASCII の安全な 1 セグメント**にする。
- 期間の日付は **`period_start` の UTC 日付**（`YYYY-MM-DD`）を 1 つ含めればよい（タイムゾーン表示設定とは独立し、ファイル名の一意性・並び替え用）。

- [ ] **Step 1: 失敗するテストを書く**

`buildDigestDownloadFilename.test.ts` を追加し、**まだ存在しない** `buildDigestDownloadFilename` を import。上記契約を満たす最小の `it` を 2〜3 本（正常系 + `kind` にスラッシュが入る異常系）。

```ts
import { describe, expect, it } from 'vitest'
import { buildDigestDownloadFilename } from './buildDigestDownloadFilename'
import type { DigestRead } from '../../api/schemas'

function digestFixture(overrides: Partial<DigestRead>): DigestRead {
  return {
    id: 1,
    period_start: '2026-03-28T00:00:00Z',
    period_end: '2026-03-29T00:00:00Z',
    kind: 'daily',
    body_markdown: '',
    status: 'ok',
    error_message: null,
    llm_model: null,
    created_at: '2026-03-29T12:00:00Z',
    ...overrides,
  }
}

describe('buildDigestDownloadFilename', () => {
  it('ends with .md and contains id and sanitized kind', () => {
    const name = buildDigestDownloadFilename(
      digestFixture({ id: 42, kind: 'daily' }),
    )
    expect(name).toMatch(/^digest-42-daily-2026-03-28\.md$/)
  })

  it('sanitizes kind for filesystem safety', () => {
    const name = buildDigestDownloadFilename(
      digestFixture({ id: 1, kind: 'we/ird:k ind' }),
    )
    expect(name).not.toMatch(/[\\/]/)
    expect(name.endsWith('.md')).toBe(true)
  })
})
```

（日付プレフィックスの正確な正規表現は実装確定後に合わせる。）

- [ ] **Step 2: RED を確認**

Run:

```bash
cd frontend && npm test -- src/panels/digests/buildDigestDownloadFilename.test.ts
```

Expected: **失敗**（`buildDigestDownloadFilename` が未定義または import 解決エラー）。

- [ ] **Step 3: 最小実装**

`buildDigestDownloadFilename.ts` に純関数を実装（`period_start` は `T` で split するか `slice(0, 10)` で UTC 日付部のみ使用）。

- [ ] **Step 4: GREEN を確認**

Run:

```bash
cd frontend && npm test -- src/panels/digests/buildDigestDownloadFilename.test.ts
```

Expected: **PASS**。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/panels/digests/buildDigestDownloadFilename.ts frontend/src/panels/digests/buildDigestDownloadFilename.test.ts
git commit -m "feat(frontend): add buildDigestDownloadFilename for digest export"
```

---

### Task 2: `getDigestBodyMarkdownForDisplay` — TDD（切り出し）

**Files:**

- Create: [`frontend/src/panels/digests/getDigestBodyMarkdownForDisplay.ts`](../../frontend/src/panels/digests/getDigestBodyMarkdownForDisplay.ts)
- Create: [`frontend/src/panels/digests/getDigestBodyMarkdownForDisplay.test.ts`](../../frontend/src/panels/digests/getDigestBodyMarkdownForDisplay.test.ts)
- Modify: [`frontend/src/panels/digests/DigestsPanel.tsx`](../../frontend/src/panels/digests/DigestsPanel.tsx)（**テストが GREEN になってから**、内部の `displayMarkdownForDigest` を削除して import に置換）

**契約:** 現行 [`DigestsPanel.tsx`](../../frontend/src/panels/digests/DigestsPanel.tsx) 17–20 行と**同じ入出力**。

```ts
// 期待する実装（GREEN 後に DigestsPanel がこれを使う）
export function getDigestBodyMarkdownForDisplay(d: DigestRead): string {
  const raw = d.llm_model != null ? d.body_markdown : stripLlmDigestSection(d.body_markdown)
  return repairPipeTablesForGfm(raw)
}
```

- [ ] **Step 1: 失敗するテストを書く**

- `llm_model: null` かつ `body_markdown` に `\n## LLM 要約\n` が含まれる → 返り値に `## LLM 要約` を含まない（[`stripLlmDigestSection`](../../frontend/src/panels/digests/stripLlmDigestSection.ts) の契約に従う）。
- `llm_model: 'gpt-4'` なら `## LLM 要約` 以降も残る。

- [ ] **Step 2: RED を確認**

```bash
cd frontend && npm test -- src/panels/digests/getDigestBodyMarkdownForDisplay.test.ts
```

Expected: **FAIL**（モジュール未作成）。

- [ ] **Step 3: 最小実装**

`getDigestBodyMarkdownForDisplay.ts` を追加（上記スニペット）。`stripLlmDigestSection` / `repairPipeTablesForGfm` を import。

- [ ] **Step 4: GREEN を確認**

```bash
cd frontend && npm test -- src/panels/digests/getDigestBodyMarkdownForDisplay.test.ts
```

- [ ] **Step 5: DigestsPanel をリファクタ**

`DigestsPanel.tsx` からローカル関数 `displayMarkdownForDigest` を削除し、`getDigestBodyMarkdownForDisplay` を import。表示挙動は変えない。

```bash
cd frontend && npm test -- src/panels/digests/DigestsPanel.test.tsx
```

Expected: **既存テストすべて PASS**。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/panels/digests/getDigestBodyMarkdownForDisplay.ts frontend/src/panels/digests/getDigestBodyMarkdownForDisplay.test.ts frontend/src/panels/digests/DigestsPanel.tsx
git commit -m "refactor(frontend): extract getDigestBodyMarkdownForDisplay for reuse"
```

---

### Task 3: `downloadTextFile` — TDD

**Files:**

- Create: [`frontend/src/utils/downloadTextFile.ts`](../../frontend/src/utils/downloadTextFile.ts)
- Create: [`frontend/src/utils/downloadTextFile.test.ts`](../../frontend/src/utils/downloadTextFile.test.ts)

**契約:** [`downloadJsonFile`](../../frontend/src/utils/downloadJsonFile.ts) と同様に、`filename`・`content` を受け取り、**同期的に**ダウンロードをトリガーする。MIME は `text/markdown` または `text/plain;charset=utf-8` のどちらか一つに統一（プロジェクト内で一貫すればよい）。

- [ ] **Step 1: 失敗するテストを書く**

`URL.createObjectURL` を `vi.spyOn(globalThis.URL, 'createObjectURL')` でラップし、`downloadTextFile('x.md', 'hello')` 呼び出し後:

- `createObjectURL` が **1 回以上**呼ばれる。
- 渡された `Blob` の `text()` が `'hello'` と一致する（`await blob.text()`）。

`document.createElement('a')` に対して `click` が呼ばれたことを `vi.spyOn(HTMLAnchorElement.prototype, 'click')` 等で確認してもよい（環境によるため、**Blob 内容 + createObjectURL** を主検証にする）。

- [ ] **Step 2: RED を確認**

```bash
cd frontend && npm test -- src/utils/downloadTextFile.test.ts
```

- [ ] **Step 3: 最小実装**

[`downloadJsonFile.ts`](../../frontend/src/utils/downloadJsonFile.ts) をコピーして `Blob([content], { type: ... })` に変更。

- [ ] **Step 4: GREEN を確認**

```bash
cd frontend && npm test -- src/utils/downloadTextFile.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/downloadTextFile.ts frontend/src/utils/downloadTextFile.test.ts
git commit -m "feat(frontend): add downloadTextFile utility"
```

---

### Task 4: UI — 「Markdown をダウンロード」ボタン + 結合テスト

**Files:**

- Modify: [`frontend/src/panels/digests/DigestsPanel.tsx`](../../frontend/src/panels/digests/DigestsPanel.tsx)
- Modify: [`frontend/src/panels/digests/DigestsPanel.test.tsx`](../../frontend/src/panels/digests/DigestsPanel.test.tsx)
- Modify（任意）: [`frontend/src/App.css`](../../frontend/src/App.css)

- [ ] **Step 1: 失敗するテストを書く**

`DigestsPanel.test.tsx` に、一覧モックで 1 件選んだあと:

- `screen.getByRole('button', { name: /Markdown をダウンロード/i })` が **存在する**。
- クリック後、`URL.createObjectURL` が呼ばれる（または `downloadTextFile` を `vi.mock` して呼び出し引数 `filename` / `content` が期待どおり）。

**注意:** 先に `downloadTextFile` を **モックしない**で統合に近い検証をするか、**`downloadTextFile` を mock** して「ボタンが正しい引数で util を呼ぶ」かを選ぶ。YAGNI なら **mock `downloadTextFile`** でボタンワイヤリングのみ検証し、Blob 詳細は Task 3 に任せる。

- [ ] **Step 2: RED を確認**

```bash
cd frontend && npm test -- src/panels/digests/DigestsPanel.test.tsx
```

Expected: **FAIL**（ボタン未実装）。

- [ ] **Step 3: 最小実装**

`SelectedDigestDetail` 内（メタ情報の下、Markdown 本文の上が読みやすい）にボタンを追加:

- `onClick`: `downloadTextFile(buildDigestDownloadFilename(selected), getDigestBodyMarkdownForDisplay(selected))`
- `type="button"`、`className` は既存 `btn btn--gray` 等に合わせる。

- [ ] **Step 4: GREEN を確認**

```bash
cd frontend && npm test -- src/panels/digests/
cd frontend && npm run lint
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/panels/digests/DigestsPanel.tsx frontend/src/panels/digests/DigestsPanel.test.tsx frontend/src/App.css
git commit -m "feat(frontend): add digest markdown download button"
```

---

### Task 5: 回帰確認（必須）

- [ ] **フロント全体テスト**

```bash
cd frontend && npm test
```

Expected: **全 PASS**。

- [ ] **ビルド**

```bash
cd frontend && npm run build
```

Expected: **エラーなし**。

---

## Plan Review Loop（任意だが推奨）

1. `plan-document-reviewer` サブエージェント（プロジェクトにあれば）に、本ドキュメントパスと関連 spec パスを渡してレビュー依頼。
2. 指摘があれば本ファイルを修正し、再レビュー（最大 3 回）。

---

## Execution Handoff

Plan complete and saved to [`docs/superpowers/plans/2026-03-29-digest-markdown-download.md`](2026-03-29-digest-markdown-download.md).

**実行オプション（実装を始めるとき）:**

1. **Subagent-Driven（推奨）** — タスクごとに新しいサブエージェントを起動し、タスク間でレビュー。必須サブスキル: **`@superpowers:subagent-driven-development`**。
2. **Inline Execution** — 同一セッションでチェックポイント付きバッチ実行。必須サブスキル: **`@superpowers:executing-plans`**。

どちらで進めるか選んでください。
