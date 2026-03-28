# ダイジェスト参照画面（フロントエンド）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: `**@superpowers:subagent-driven-development`**（推奨）または `**@superpowers:executing-plans**`。ステップはチェックボックス（`- [ ]`）で追跡する。
>
> **TDD:** `**@superpowers:test-driven-development`** を前提とする。各機能単位で **失敗するテスト → 最小実装 → グリーン → リファクタ** の順を守る。コミットは **タスク単位またはグリーンごと**（頻繁に）行う。

**Goal:** 保存済みダイジェストを **一覧・本文（Markdown / GFM 表）で参照**するメインタブ「ダイジェスト」を追加する。LLM 要約が **記録されている**場合（`llm_model` が非 null）は本文に **含めて表示**し、要約が **無い**場合は **`## LLM 要約` ブロックは表示しない**。`POST /api/digests/run` は UI から呼ばない。

**Architecture:** 既存 API `[GET /api/digests](../../src/vcenter_event_assistant/api/routes/digests.py)`・`[GET /api/digests/{id}](../../src/vcenter_event_assistant/api/routes/digests.py)` を `[frontend/src/api.ts](../../frontend/src/api.ts)` の `apiGet` で取得する。レスポンスは Zod で検証（`[frontend/src/api/schemas.ts](../../frontend/src/api/schemas.ts)`）。本文は `react-markdown` + `remark-gfm` で描画する。**`llm_model` が非 null（LLM 要約が記録されている）のときだけ** `body_markdown` に含まれる **`## LLM 要約` 以降を含めて全文表示**する。**`llm_model` が null のときは `## LLM 要約` ブロックを表示しない**（本文は当該見出しの **直前まで**に切り詰めてからレンダリングする。データ不整合で本文に見出しだけ残っていても出さない）。詳細エリアでは `llm_model` が非 null のとき、本文の外に **「LLM 要約あり（モデル名）」** のような短いメタ表示を追加する。ナビは `[frontend/src/App.tsx](../../frontend/src/App.tsx)` のタブ state に `digests` を追加する（ルーターは導入しない）。

**Tech Stack:** React 19、TypeScript、Vite、Vitest、Testing Library（既存）、Zod、`react-markdown`、`remark-gfm`、既存 `[App.css](../../frontend/src/App.css)` 変数。

**前提（スコープ）:** 一覧・表示のみ。タブは「概要・イベント・グラフ・**ダイジェスト**・設定」の並び。

**関連仕様・API:** バックエンドスキーマ `[DigestRead](../../src/vcenter_event_assistant/api/schemas.py)`。ダイジェスト本文テンプレートは GFM テーブルを含む `[digest.md.j2](../../src/vcenter_event_assistant/templates/digest.md.j2)`。

### LLM 要約の表示（必須要件）

| データ | 意味 | UI での扱い |
| ------ | ---- | ----------- |
| `body_markdown` | テンプレート全文 +（LLM 成功時）末尾に `## LLM 要約` 以下が **連結**された 1 本の Markdown | **`llm_model` が非 null:** そのまま全文を `react-markdown` に渡し、見出し「LLM 要約」と箇条書きを表示する。**`llm_model` が null:** 先頭から **最初の行 `## LLM 要約`（Markdown の見出し）より前**までだけをレンダリングし、**`## LLM 要約` ブロックは出さない**（要約が存在しない扱い）。 |
| `llm_model` | API キーがあり、かつ LLM 呼び出しが成功したときのみ非 null（`[digest_run.py](../../src/vcenter_event_assistant/services/digest_run.py)`） | 上記の切り詰め可否の **判定**に使う。非 null のとき「LLM 要約あり」＋モデル名を **メタ情報**として表示。 |
| `error_message` | 例: LLM 失敗時は「LLM 要約は省略（…）」など（`status` は `ok` のままの場合あり） | 既存どおり **警告表示**。通常は本文に `## LLM 要約` は含まれない。 |

**切り詰めの実装:** 純関数（例: `stripLlmDigestSection(markdown: string): string`）で、文字列内の **`\\n## LLM 要約`（行頭の見出し）より前**を返す。見出しが無ければ全文を返す。`llm_model === null` のときだけ表示用 Markdown に適用する。別カード用に要約だけ抽出する処理は **不要**（YAGNI）。一覧行にモデル名を出すかは任意（詳細にメタ必須）。

---

## ブランチ方針

- **ベース:** `main`（最新を `git pull` 済みであること）。
- **ブランチ名例:** `feat/frontend-digests-view`
- 本計画の **Task 0** でブランチを切り、以降のコミットはすべてこのブランチ上で行う。マージは PR またはローカルマージ（プロジェクト運用に従う）。

---

## ファイル構成


| ファイル                                                                                                               | 責務                                                                                       |
| ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| `[frontend/package.json](../../frontend/package.json)`                                                             | `react-markdown`、`remark-gfm` 依存追加                                                       |
| `[frontend/package-lock.json](../../frontend/package-lock.json)`                                                   | lock 更新（`npm install`）                                                                   |
| `[frontend/src/api/schemas.ts](../../frontend/src/api/schemas.ts)`                                                 | `digestReadSchema`、`digestListResponseSchema`、`parseDigestListResponse`（または同等の export 名） |
| `[frontend/src/api/schemas.test.ts](../../frontend/src/api/schemas.test.ts)`                                       | ダイジェスト用パースのテスト                                                                           |
| `[frontend/src/panels/digests/stripLlmDigestSection.ts](../../frontend/src/panels/digests/stripLlmDigestSection.ts)`（新規・任意で `utils` 配下） | `llm_model` が null のとき表示から除外するため、`body_markdown` から `## LLM 要約` 見出し以降を落とす純関数（単体テスト必須） |
| `[frontend/src/panels/digests/stripLlmDigestSection.test.ts](../../frontend/src/panels/digests/stripLlmDigestSection.test.ts)`（新規） | 見出しあり・なし・境界のテスト |
| `[frontend/src/panels/digests/DigestsPanel.tsx](../../frontend/src/panels/digests/DigestsPanel.tsx)`（新規）           | 一覧取得、ページング、行選択、Markdown 表示（**`llm_model` に応じて全文 or 切り詰め**）、`llm_model` メタ、`status === 'error'` 時の `error_message` 表示 |
| `[frontend/src/panels/digests/DigestsPanel.test.tsx](../../frontend/src/panels/digests/DigestsPanel.test.tsx)`（新規） | モック `fetch` による一覧・詳細・エラー表示。**`llm_model` あり + `## LLM 要約` 本文**で見出しが出ること。**`llm_model` が null かつ本文に `## LLM 要約` が含まれる異常系**でも見出しが **DOM に出ない**こと |
| `[frontend/src/App.tsx](../../frontend/src/App.tsx)`                                                               | タブ `digests` とパネルマウント                                                                    |
| `[frontend/src/App.css](../../frontend/src/App.css)`                                                               | `.digest-markdown` 等（見出し・表・コードブロックの余白。既存トークンに合わせる）                                       |
| `[frontend/e2e/app-smoke.spec.ts](../../frontend/e2e/app-smoke.spec.ts)`（または既存 smoke）                              | 任意: 「ダイジェスト」タブが開けること                                                                     |


**変更しないもの:** バックエンド API・DB モデル（本機能はフロントのみ）。

---

### Task 0: ブランチ作成

**Files:**

- なし（git のみ）
- **Step 1:** `main` で作業ツリーがクリーンであることを確認する。

Run:

```bash
git status
```

Expected: コミット予定の無関係な変更がないこと。

- **Step 2:** フィーチャーブランチを作成してチェックアウトする。

Run:

```bash
git checkout main
git pull
git checkout -b feat/frontend-digests-view
```

Expected: 現在ブランチが `feat/frontend-digests-view`。

- **Step 3:** （任意）空コミットや README 以外の変更はしない。ブランチのみプッシュする場合は `git push -u origin feat/frontend-digests-view`。

---

### Task 1: `parseDigestListResponse`（Zod）— TDD

**Files:**

- Modify: `[frontend/src/api/schemas.ts](../../frontend/src/api/schemas.ts)`
- Modify: `[frontend/src/api/schemas.test.ts](../../frontend/src/api/schemas.test.ts)`
- **Step 1: 失敗するテストを書く**

`[frontend/src/api/schemas.test.ts](../../frontend/src/api/schemas.test.ts)` に、**まだ存在しない** `parseDigestListResponse`（仮名）を import し、次を検証する `describe` を追加する。

- 最小の合法 JSON（`items` が 1 件、`total` が数値）を渡すと、`items[0].id`・`body_markdown`・`status` 等が取れる。
- `items` が空でも `total` が正しい。
- 不正なシェイプでは `ZodError` または既存パターンに合わせた失敗になる。

例（実装時に API フィールド名を `[DigestRead](../../src/vcenter_event_assistant/api/schemas.py)` と完全一致させること）:

```ts
import { describe, expect, it } from 'vitest'
import { parseDigestListResponse } from './schemas'

describe('parseDigestListResponse', () => {
  it('parses digest list envelope', () => {
    const raw = {
      items: [
        {
          id: 1,
          period_start: '2026-03-27T00:00:00Z',
          period_end: '2026-03-28T00:00:00Z',
          kind: 'daily',
          body_markdown: '# Hello',
          status: 'ok',
          error_message: null,
          llm_model: 'x',
          created_at: '2026-03-28T01:00:00Z',
        },
      ],
      total: 1,
    }
    const parsed = parseDigestListResponse(raw)
    expect(parsed.total).toBe(1)
    expect(parsed.items[0]?.body_markdown).toBe('# Hello')
  })
})
```

- **Step 2: テストが失敗することを確認する**

Run:

```bash
cd frontend && npm run test -- --run src/api/schemas.test.ts
```

Expected: `parseDigestListResponse is not a function` または import エラーで **FAIL**。

- **Step 3: 最小実装する**

`[frontend/src/api/schemas.ts](../../frontend/src/api/schemas.ts)` に `digestReadSchema`（`z.object({ ... })`）と `digestListResponseSchema`、`parseDigestListResponse(raw: unknown)` を追加する。日時は API が ISO 文字列で返すため `z.string()` でよい（表示はパネル側で `formatIsoInTimeZone`）。

- **Step 4: テストが通ることを確認する**

Run:

```bash
cd frontend && npm run test -- --run src/api/schemas.test.ts
```

Expected: **PASS**。

- **Step 5: Commit**

```bash
git add frontend/src/api/schemas.ts frontend/src/api/schemas.test.ts
git commit -m "test(frontend): add digest list Zod parse with TDD"
```

---

### Task 2: 依存追加（`react-markdown` / `remark-gfm`）

**Files:**

- Modify: `[frontend/package.json](../../frontend/package.json)`
- Modify: `[frontend/package-lock.json](../../frontend/package-lock.json)`
- **Step 1:** リポジトリルートまたは `frontend` でロックファイルに従いパッケージを追加する。

Run:

```bash
cd frontend && npm install react-markdown remark-gfm
```

- **Step 2:** `npm run build` が通ることを確認する。

Run:

```bash
cd frontend && npm run build
```

Expected: **成功**（まだパネル未使用でもよい）。

- **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): add react-markdown and remark-gfm for digests"
```

---

### Task 2.5: `stripLlmDigestSection`（純関数）— TDD

**Files:**

- Create: `[frontend/src/panels/digests/stripLlmDigestSection.ts](../../frontend/src/panels/digests/stripLlmDigestSection.ts)`
- Create: `[frontend/src/panels/digests/stripLlmDigestSection.test.ts](../../frontend/src/panels/digests/stripLlmDigestSection.test.ts)`

**仕様:** 文字列のうち、**最初に現れる行 `## LLM 要約`（行全体がその見出し）より前**を返す。該当行が無いときは入力をそのまま返す。先頭の `## LLM 要約` のみ対象とし、テンプレ内に同じ文字列が誤って含まれるケースは本計画では想定しない（必要なら将来 `\n## LLM 要約\n` パターンに限定する）。

- **Step 1:** 失敗するテスト（見出しありで前半のみ、見出しなしで全文）を書く。
- **Step 2:** `npm run test` で FAIL を確認。
- **Step 3:** 最小実装。
- **Step 4:** PASS を確認。
- **Step 5: Commit**

```bash
git add frontend/src/panels/digests/stripLlmDigestSection.ts frontend/src/panels/digests/stripLlmDigestSection.test.ts
git commit -m "test(frontend): add stripLlmDigestSection for digest view"
```

---

### Task 3: `DigestsPanel` — TDD（モック fetch）

**Files:**

- Create: `[frontend/src/panels/digests/DigestsPanel.tsx](../../frontend/src/panels/digests/DigestsPanel.tsx)`
- Create: `[frontend/src/panels/digests/DigestsPanel.test.tsx](../../frontend/src/panels/digests/DigestsPanel.test.tsx)`
- Modify: `[frontend/src/App.css](../../frontend/src/App.css)`
- **Step 1: 失敗するテストを書く**

`[frontend/src/panels/digests/DigestsPanel.test.tsx](../../frontend/src/panels/digests/DigestsPanel.test.tsx)` で `globalThis.fetch` をモックし、`/api/digests?` を呼ぶと一覧に `kind` や期間ラベルが表示されること、行クリックで本文に見出しテキストが出ること、`**status: 'error'`** のとき `error_message` が表示されることを検証する。コンポーネント名は `DigestsPanel`。

**追加（LLM 要約）:**

- **`llm_model` あり:** モック 1 件目に `body_markdown: '# T\n\n## LLM 要約\n\n- 要点A'` と `llm_model: 'gpt-4o-mini'` を含め、詳細表示後に **「LLM 要約」見出しまたは「要点A」** が DOM に含まれること、**メタ表示（要約あり・モデル名）**が含まれることを検証する。
- **`llm_model` なし:** 同様の `body_markdown` で **`llm_model: null`** のとき、**「LLM 要約」見出しが DOM に無い**こと（テンプレ部分 `# T` のみ等が見えること）を検証する。

初期 import でコンポーネントが無ければ **FAIL**。

- **Step 2: テストが失敗することを確認する**

Run:

```bash
cd frontend && npm run test -- --run src/panels/digests/DigestsPanel.test.tsx
```

Expected: **FAIL**。

- **Step 3: 実装する**
- `apiGet('/api/digests?limit=50&offset=0')`（`limit`/`offset` は定数化）→ `parseDigestListResponse`。
- ページング: `offset` state、`total` に応じて「前へ」「次へ」（日本語ラベル）。
- 表示用 Markdown: `const md = selected.llm_model != null ? selected.body_markdown : stripLlmDigestSection(selected.body_markdown)` を `ReactMarkdown` + `remarkGfm` に渡す。ラッパーに `className="digest-markdown"`（または `panel` 内の子）。
- **`llm_model` が null でないとき:** 本文の上または横にメタ行を出す（例: `LLM 要約あり（{llm_model}）`）。**`llm_model` が null のときはメタ行も出さない**（要約なし）。
- `error_message` が null でないときは従来どおり警告表示（LLM 省略時もユーザーが気づけるようにする）。
- `[useTimeZone](../../frontend/src/datetime/useTimeZone.ts)` と `[formatIsoInTimeZone](../../frontend/src/datetime/formatIsoInTimeZone.ts)` で期間・`created_at` を表示（`[SummaryPanel](../../frontend/src/panels/summary/SummaryPanel.tsx)` に揃える）。
- `onError` で `[toErrorMessage](../../frontend/src/utils/errors.ts)` を親へ。
- **Step 4: テストが通ることを確認する**

Run:

```bash
cd frontend && npm run test -- --run src/panels/digests/DigestsPanel.test.tsx
```

Expected: **PASS**。

- **Step 5: スタイル**

`[frontend/src/App.css](../../frontend/src/App.css)` に `.digest-markdown table`、見出し、`pre` の余白を追加（ダークテーマ変数に合わせる）。

- **Step 6: Commit**

```bash
git add frontend/src/panels/digests/DigestsPanel.tsx frontend/src/panels/digests/DigestsPanel.test.tsx frontend/src/App.css
git commit -m "feat(frontend): add DigestsPanel with markdown and tests"
```

---

### Task 4: `App.tsx` への組み込み

**Files:**

- Modify: `[frontend/src/App.tsx](../../frontend/src/App.tsx)`
- **Step 1: 失敗するテストを追加する（任意だが推奨）**

`[frontend/src/App.error.test.tsx](../../frontend/src/App.error.test.tsx)` 等の既存パターンがあれば、タブ「ダイジェスト」が DOM に存在することを 1 テスト追加する。なければ **手動確認**に回す。

- **Step 2: 実装**
- `type Tab = ... | 'digests'`
- `nav` のボタン配列に `digests` とラベル「ダイジェスト」を追加（**概要・イベント・グラフ・ダイジェスト・設定**）。
- `tab === 'digests'` で `<DigestsPanel onError={setErr} />`
- **Step 3: 全体テストとビルド**

Run:

```bash
cd frontend && npm run test -- --run
cd frontend && npm run build
```

Expected: **PASS** / **成功**。

- **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.error.test.tsx
git commit -m "feat(frontend): add digests main tab"
```

（テスト未変更なら `App.tsx` のみ）

---

### Task 5: E2E（任意）

**Files:**

- Modify: `[frontend/e2e/app-smoke.spec.ts](../../frontend/e2e/app-smoke.spec.ts)` 等
- **Step 1:** 既存 smoke に「ダイジェスト」タブをクリックし、`networkidle` または短い `waitForTimeout` の後にパネル用の見出しまたは `main` 内のテキストが期待どおりであることを追加する。
- **Step 2:**

Run:

```bash
cd frontend && npm run build && npx playwright test e2e/app-smoke.spec.ts
```

（プロジェクトの既存 E2E コマンドに合わせる。README 参照。）

- **Step 3: Commit**

```bash
git add frontend/e2e/app-smoke.spec.ts
git commit -m "test(e2e): smoke opens digests tab"
```

---

### Task 6: ドキュメント（任意・短く）

**Files:**

- Modify: `[docs/frontend.md](../../docs/frontend.md)`
- **Step 1:** 「ダイジェスト」タブの説明を 1〜2 文追加する（スクリーンショットは別タスク可）。
- **Step 2: Commit**

```bash
git add docs/frontend.md
git commit -m "docs(frontend): document digests tab"
```

---

## 完了時の検証コマンド（一覧）

```bash
cd frontend && npm run test -- --run
cd frontend && npm run build
cd frontend && npm run lint
```

バックエンド起動済みで UI を手動確認する場合:

```bash
# 別ターミナルで API を起動後
cd frontend && npm run dev
```

ブラウザで「ダイジェスト」タブ → 一覧と Markdown 本文が表示されること。

---

## Plan review loop（エージェント向け）

1. 本ファイルを `**plan-document-reviewer**` サブエージェントに渡しレビューする（セッション履歴ではなく本ファイルと関連パスを明示）。
2. 指摘があれば本ファイルを修正し、最大 3 回まで再レビュー。
3. 人間レビュー後、実装へ進む。

---

## 実装完了後の進め方（人間向け）

Plan complete and saved to `[docs/superpowers/plans/2026-03-28-digests-frontend-tdd.md](2026-03-28-digests-frontend-tdd.md)`.

**実行オプション:**

1. **Subagent-Driven（推奨）** — タスクごとに新しいサブエージェントを起動し、タスク間にレビュー。 `**@superpowers:subagent-driven-development`** を必須とする。
2. **Inline Execution** — 同一セッションで `**@superpowers:executing-plans`** に従いチェックポイント付きで一括実行。

どちらで進めますか。