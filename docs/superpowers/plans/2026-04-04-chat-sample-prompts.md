# チャット・サンプル質問（複数選択・設定でカスタム追加）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **実装時は superpowers:test-driven-development を遵守する**（本節「TDD」参照）。

**Goal:** チャットパネルで **複数のサンプル質問をトグル選択**し、「下書きに挿入」で **定義順・`\n\n` 区切り**で textarea に反映する（送信はしない）。既存下書きは **末尾追記**。その後、**設定の新サブタブ**から **カスタムサンプルを CRUD** し **localStorage** に保存、チャットのチップ一覧に **既定＋カスタム**で表示する。

**Architecture:** 挿入ロジックは **純関数**（[`appendSelectedChatSampleTextsToDraft`](../../frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.ts)）に切り出し単体テストする。既定文は定数モジュール。フェーズ2では **カスタム配列だけ**を Zod で検証して localStorage へ保存し、[`ChatCustomSamplePromptsProvider`](../../frontend/src/preferences/ChatCustomSamplePromptsProvider.tsx)（新規）が [`SummaryTopNotableMinScoreProvider`](../../frontend/src/preferences/SummaryTopNotableMinScoreProvider.tsx) と同様に **状態＋永続化**を提供する。[`ChatPanel`](../../frontend/src/panels/chat/ChatPanel.tsx) は hook で **表示用プロンプト一覧**（既定＋カスタムのうち **label・text が非空**の行のみ）を受け取り、トグル＋挿入ボタンを描画する。

**Tech Stack:** React 19、TypeScript、Vite、Vitest、Testing Library、Zod 4、localStorage（キーは `vea.` プレフィックス）。

---

## TDD（必須）

本計画の各タスクは **Red → Green → Refactor** で進める。**本番コードをテストより先に書かない**。

| 段階 | 内容 |
|------|------|
| **RED** | 振る舞い 1 つにつけ、**先に**失敗するテストを追加する。 |
| **Verify RED** | `npm run test -- --run path/to/file.test.ts` を実行し、**意図どおり失敗**することを確認する（import エラーで失敗していないこと）。 |
| **GREEN** | テストを通す **最小** の実装だけ加える。 |
| **Verify GREEN** | 対象テストが PASS。必要なら `npm run test -- --run` でフロント全体。 |
| **REFACTOR** | GREEN のあと、重複削除・名前整理のみ。振る舞いを変えない。 |

**検証チェックリスト（完了前）:** 新規の公開関数・UI 振る舞いにテストがあること。**新規振る舞いでは RED を一度は目視**したこと。

---

## ファイル一覧

| 操作 | パス |
|------|------|
| 新規 | [`frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.ts`](../../frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.ts)（純関数） |
| 新規 | [`frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.test.ts`](../../frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.test.ts) |
| 新規 | [`frontend/src/panels/chat/chatSamplePromptTypes.ts`](../../frontend/src/panels/chat/chatSamplePromptTypes.ts)（共有型） |
| 新規 | [`frontend/src/panels/chat/defaultChatSamplePrompts.ts`](../../frontend/src/panels/chat/defaultChatSamplePrompts.ts)（既定 4 件程度） |
| 変更 | [`frontend/src/panels/chat/ChatPanel.tsx`](../../frontend/src/panels/chat/ChatPanel.tsx)（トグル・挿入・`useChatCustomSamplePrompts`） |
| 変更 | [`frontend/src/panels/chat/ChatPanel.test.tsx`](../../frontend/src/panels/chat/ChatPanel.test.tsx)（Provider でラップ・シナリオテスト） |
| 変更 | [`frontend/src/App.css`](../../frontend/src/App.css)（`.chat-panel__sample-prompts` 等） |
| 新規 | [`frontend/src/preferences/chatCustomSamplePromptsStorage.ts`](../../frontend/src/preferences/chatCustomSamplePromptsStorage.ts)（Zod read/write） |
| 新規 | [`frontend/src/preferences/chatCustomSamplePromptsStorage.test.ts`](../../frontend/src/preferences/chatCustomSamplePromptsStorage.test.ts) |
| 新規 | [`frontend/src/preferences/chatCustomSamplePromptsContext.tsx`](../../frontend/src/preferences/chatCustomSamplePromptsContext.tsx) |
| 新規 | [`frontend/src/preferences/useChatCustomSamplePrompts.ts`](../../frontend/src/preferences/useChatCustomSamplePrompts.ts) |
| 新規 | [`frontend/src/preferences/ChatCustomSamplePromptsProvider.tsx`](../../frontend/src/preferences/ChatCustomSamplePromptsProvider.tsx) |
| 新規 | [`frontend/src/panels/settings/ChatCustomSamplePromptsPanel.tsx`](../../frontend/src/panels/settings/ChatCustomSamplePromptsPanel.tsx) |
| 新規 | [`frontend/src/panels/settings/ChatCustomSamplePromptsPanel.test.tsx`](../../frontend/src/panels/settings/ChatCustomSamplePromptsPanel.test.tsx) |
| 変更 | [`frontend/src/App.tsx`](../../frontend/src/App.tsx)（Provider・サブタブ・パネル） |
| 変更 | [`frontend/src/components/settings-subtab-icons.tsx`](../../frontend/src/components/settings-subtab-icons.tsx)（`SettingsSubTabId` 拡張・アイコン） |
| 変更 | [`frontend/src/App.settings-subtabs.test.tsx`](../../frontend/src/App.settings-subtabs.test.tsx)（5 サブタブへ更新） |

---

### Task 1: `appendSelectedChatSampleTextsToDraft`（純関数）を TDD で追加

**Files:**
- 新規: [`frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.test.ts`](../../frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.test.ts)
- 新規: [`frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.ts`](../../frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.ts)

- [ ] **Step 1: 失敗するテストファイルを追加（RED）**

`appendSelectedChatSampleTextsToDraft.test.ts` を新規作成し、次の内容とする（インポート先モジュールはまだ無いため RED になる）。

```typescript
import { describe, expect, it } from 'vitest'

import { appendSelectedChatSampleTextsToDraft } from './appendSelectedChatSampleTextsToDraft'

describe('appendSelectedChatSampleTextsToDraft', () => {
  const ordered = [
    { id: 'a', text: 'First' },
    { id: 'b', text: 'Second' },
  ]

  it('選択 id を一覧の定義順で連結し、\\n\\n で区切って空下書きへ入れる', () => {
    expect(appendSelectedChatSampleTextsToDraft('', ordered, new Set(['b', 'a']))).toBe(
      'First\n\nSecond',
    )
  })

  it('既存下書きがあるとき末尾に \\n\\n で追記する', () => {
    expect(appendSelectedChatSampleTextsToDraft('Hello', ordered, new Set(['a']))).toBe(
      'Hello\n\nFirst',
    )
  })

  it('選択が空のとき下書きを変えない', () => {
    expect(appendSelectedChatSampleTextsToDraft('Hi', ordered, new Set())).toBe('Hi')
  })

  it('各 text は trim してから連結する', () => {
    const rows = [{ id: 'x', text: '  body  ' }]
    expect(appendSelectedChatSampleTextsToDraft('', rows, new Set(['x']))).toBe('body')
  })

  it('trim 後に空になる text は連結から除外する', () => {
    const rows = [
      { id: 'a', text: 'OK' },
      { id: 'b', text: '   ' },
    ]
    expect(appendSelectedChatSampleTextsToDraft('', rows, new Set(['a', 'b']))).toBe('OK')
  })
})
```

- [ ] **Step 2: RED を確認**

```bash
cd /Users/moriyama/git/vcenter-event-assistant/frontend && npm run test -- --run src/panels/chat/appendSelectedChatSampleTextsToDraft.test.ts
```

期待: モジュールが見つからない、または関数未定義で **失敗**。

- [ ] **Step 3: 最小実装（GREEN）**

`appendSelectedChatSampleTextsToDraft.ts` を新規作成する。

```typescript
const DOUBLE_NEWLINE = '\n\n'

/**
 * サンプル質問のうち選択されたものを、一覧の定義順で本文だけ抽出し `\n\n` で連結して下書きへ追記する。
 */
export function appendSelectedChatSampleTextsToDraft(
  currentDraft: string,
  orderedItems: readonly { id: string; text: string }[],
  selectedIds: ReadonlySet<string>,
): string {
  const texts = orderedItems
    .filter((item) => selectedIds.has(item.id))
    .map((item) => item.text.trim())
    .filter((t) => t.length > 0)
  const block = texts.join(DOUBLE_NEWLINE)
  if (!block) {
    return currentDraft
  }
  const trimmedDraft = currentDraft.trimEnd()
  if (!trimmedDraft) {
    return block
  }
  return `${trimmedDraft}${DOUBLE_NEWLINE}${block}`
}
```

- [ ] **Step 4: GREEN を確認**

```bash
cd /Users/moriyama/git/vcenter-event-assistant/frontend && npm run test -- --run src/panels/chat/appendSelectedChatSampleTextsToDraft.test.ts
```

期待: **PASS**。

- [ ] **Step 5: Commit**

```bash
cd /Users/moriyama/git/vcenter-event-assistant && git add frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.ts frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.test.ts && git commit -m "feat(chat): add draft merge helper for sample prompts"
```

---

### Task 2: 共有型と既定サンプル定数

**Files:**
- 新規: [`frontend/src/panels/chat/chatSamplePromptTypes.ts`](../../frontend/src/panels/chat/chatSamplePromptTypes.ts)
- 新規: [`frontend/src/panels/chat/defaultChatSamplePrompts.ts`](../../frontend/src/panels/chat/defaultChatSamplePrompts.ts)

- [ ] **Step 1: 型のみ追加（テストは Task 3 で間接的にカバー）**

`chatSamplePromptTypes.ts`:

```typescript
/**
 * チャットに表示するサンプル質問 1 件（既定・カスタム共通）。
 */
export type ChatSamplePromptRow = {
  readonly id: string
  readonly label: string
  readonly text: string
}
```

- [ ] **Step 2: 既定 4 件（日本語・VM 名に依存しない）**

`defaultChatSamplePrompts.ts`（`id` は安定キー、`label` は短く、`text` はそのまま下書きへ入る）。

```typescript
import type { ChatSamplePromptRow } from './chatSamplePromptTypes'

/** チャットパネルに出す既定サンプル（コード同梱・読み取り専用）。 */
export const DEFAULT_CHAT_SAMPLE_PROMPTS: readonly ChatSamplePromptRow[] = [
  {
    id: 'default-sample-period-summary',
    label: '期間の要約',
    text: 'この期間のイベントと傾向を、重要度が高い順に要約してください。',
  },
  {
    id: 'default-sample-power-events',
    label: '電源・可用性',
    text: '仮想マシンやホストの電源操作・可用性に関するイベントの傾向を説明してください。',
  },
  {
    id: 'default-sample-alerts',
    label: '警告・エラー',
    text: '警告やエラーに分類されそうなイベントがあれば列挙し、時系列での変化も述べてください。',
  },
  {
    id: 'default-sample-metrics-hint',
    label: 'メトリクス併用',
    text:
      '期間メトリクス（CPU・メモリ等）をコンテキストに含めたうえで、負荷やボトルネックの兆候が読み取れるか整理してください。',
  },
]
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/panels/chat/chatSamplePromptTypes.ts frontend/src/panels/chat/defaultChatSamplePrompts.ts && git commit -m "feat(chat): add default sample prompt definitions"
```

---

### Task 3: `ChatPanel` にトグル・挿入 UI と結合テスト

**Files:**
- 変更: [`frontend/src/panels/chat/ChatPanel.tsx`](../../frontend/src/panels/chat/ChatPanel.tsx)
- 変更: [`frontend/src/panels/chat/ChatPanel.test.tsx`](../../frontend/src/panels/chat/ChatPanel.test.tsx)
- 変更: [`frontend/src/App.css`](../../frontend/src/App.css)

**挙動の固定仕様:**

- `useState<ReadonlySet<string>>(new Set())` で選択 id。
- 各サンプルは `type="button"`、`aria-pressed={selectedIds.has(id)}`、`aria-label` は `サンプル「${label}」`。
- 「下書きに挿入」ボタン: `name` / ラベル文言 **下書きに挿入**。`selectedIds.size === 0` または `loading` で `disabled`。
- 挿入時: `setDraft((d) => appendSelectedChatSampleTextsToDraft(d, visibleRows, selectedIds))` のあと `setSelectedIds(new Set())`、`textarea` に `ref` して `focus()`。
- **フェーズ1:** `visibleRows` は `DEFAULT_CHAT_SAMPLE_PROMPTS` のみ（Task 4 で hook に差し替え）。
- `role="group"` `aria-label="サンプルの質問"` でチップ群をラップ。

- [ ] **Step 1: 失敗する結合テストを追加（RED）**

`ChatPanel.test.tsx` の `describe('ChatPanel')` 内に追加する（`fetch` スタブは既存と同様 `/api/vcenters` のみでよい）。

```typescript
  it('サンプルを複数選択して下書きに挿入すると定義順で \\n\\n 連結される', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.click(screen.getByRole('button', { name: 'サンプル「メトリクス併用」' }))
    fireEvent.click(screen.getByRole('button', { name: 'サンプル「期間の要約」' }))
    fireEvent.click(screen.getByRole('button', { name: '下書きに挿入' }))

    const ta = screen.getByPlaceholderText('質問を入力…') as HTMLTextAreaElement
    expect(ta.value).toContain('この期間のイベントと傾向を')
    expect(ta.value).toContain('期間メトリクス（CPU・メモリ等）')
    expect(ta.value.indexOf('この期間のイベントと傾向を')).toBeLessThan(
      ta.value.indexOf('期間メトリクス（CPU・メモリ等）'),
    )

    expect(screen.getByRole('button', { name: 'サンプル「期間の要約」' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })
```

期待: UI が無いので **失敗**。

```bash
cd /Users/moriyama/git/vcenter-event-assistant/frontend && npm run test -- --run src/panels/chat/ChatPanel.test.tsx -t 'サンプルを複数選択して下書きに挿入'
```

- [ ] **Step 2: `ChatPanel` と CSS を実装（GREEN）**

`ChatPanel.tsx` に state・グループ・ループ・挿入ハンドラを追加。`defaultChatSamplePrompts` と `appendSelectedChatSampleTextsToDraft` を import。

`App.css` に例:

```css
.chat-panel__sample-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-2);
  align-items: center;
}

.chat-panel__sample-prompts .btn--toggle[aria-pressed='true'] {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
```

トグル見た目は既存 `btn btn--gray` に `btn--toggle` を足す程度でよい。

- [ ] **Step 3: 追記テスト（RED→GREEN）**

同じ describe に **既存下書きがあるとき追記**する `it` を追加（先にテスト、実装が既に `appendSelected...` なら最初から PASS しうる → その場合はテストを先に書き、値が追記になることを断言）。

```typescript
  it('サンプル挿入は既存下書きの末尾に追記する', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/vcenters')) {
        return Promise.resolve(jsonResponse([]))
      }
      return Promise.resolve(new Response('not found', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderChat()
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByPlaceholderText('質問を入力…'), { target: { value: '既存' } })
    fireEvent.click(screen.getByRole('button', { name: 'サンプル「期間の要約」' }))
    fireEvent.click(screen.getByRole('button', { name: '下書きに挿入' }))

    const ta = screen.getByPlaceholderText('質問を入力…') as HTMLTextAreaElement
    expect(ta.value.startsWith('既存')).toBe(true)
    expect(ta.value).toContain('この期間のイベントと傾向を')
  })
```

- [ ] **Step 4: 全体テスト**

```bash
cd /Users/moriyama/git/vcenter-event-assistant/frontend && npm run test -- --run src/panels/chat/ChatPanel.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/panels/chat/ChatPanel.tsx frontend/src/panels/chat/ChatPanel.test.tsx frontend/src/App.css && git commit -m "feat(chat): multi-select sample prompts and insert into draft"
```

---

### Task 4: `loading` 中はサンプル操作不可（TDD）

**Files:**
- 変更: [`frontend/src/panels/chat/ChatPanel.test.tsx`](../../frontend/src/panels/chat/ChatPanel.test.tsx)
- 変更: [`frontend/src/panels/chat/ChatPanel.tsx`](../../frontend/src/panels/chat/ChatPanel.tsx)（無ければ `disabled` を確認）

- [ ] **Step 1: 失敗するテスト**

送信後に `/api/chat` の応答を遅延解決し、その間 `下書きに挿入` とサンプルトグルが `disabled` であることを検証する `it` を追加（既存の送信テストの `fetchMock` パターンを流用）。

- [ ] **Step 2: GREEN**

各サンプルボタンと「下書きに挿入」に `disabled={loading}` を付与済みか確認し、足りなければ追加。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/panels/chat/ChatPanel.test.tsx frontend/src/panels/chat/ChatPanel.tsx && git commit -m "fix(chat): disable sample prompts while sending"
```

---

### Task 5: localStorage + Zod（カスタムサンプルだけ保存）

**Files:**
- 新規: [`frontend/src/preferences/chatCustomSamplePromptsStorage.test.ts`](../../frontend/src/preferences/chatCustomSamplePromptsStorage.test.ts)
- 新規: [`frontend/src/preferences/chatCustomSamplePromptsStorage.ts`](../../frontend/src/preferences/chatCustomSamplePromptsStorage.ts)

- [ ] **Step 1: RED — ストレージテスト先書き**

`chatCustomSamplePromptsStorage.test.ts`:

```typescript
import { afterEach, describe, expect, it } from 'vitest'

import {
  CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY,
  readStoredChatCustomSamplePrompts,
  writeStoredChatCustomSamplePrompts,
} from './chatCustomSamplePromptsStorage'

describe('chatCustomSamplePromptsStorage', () => {
  afterEach(() => {
    localStorage.removeItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)
  })

  it('未設定時は空配列を返す', () => {
    expect(readStoredChatCustomSamplePrompts()).toEqual([])
  })

  it('正しい JSON を読み書きできる', () => {
    const rows = [
      { id: 'c1', label: 'カスタム1', text: '本文1' },
      { id: 'c2', label: 'カスタム2', text: '本文2' },
    ]
    writeStoredChatCustomSamplePrompts(rows)
    expect(readStoredChatCustomSamplePrompts()).toEqual(rows)
  })

  it('不正 JSON のときは空配列を返す', () => {
    localStorage.setItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY, '{not json')
    expect(readStoredChatCustomSamplePrompts()).toEqual([])
  })

  it('Zod で弾かれる要素は落として読む', () => {
    localStorage.setItem(
      CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY,
      JSON.stringify([{ id: '', label: 'x', text: 'y' }]),
    )
    expect(readStoredChatCustomSamplePrompts()).toEqual([])
  })
})
```

```bash
cd /Users/moriyama/git/vcenter-event-assistant/frontend && npm run test -- --run src/preferences/chatCustomSamplePromptsStorage.test.ts
```

期待: **失敗**。

- [ ] **Step 2: GREEN — 実装**

`chatCustomSamplePromptsStorage.ts`:

```typescript
import { z } from 'zod'

/** カスタムサンプル質問のみを保存する localStorage キー（既定サンプルは含めない）。 */
export const CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY = 'vea.chat_custom_sample_prompts.v1'

const rowSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  text: z.string().min(1),
})

const arraySchema = z.array(rowSchema)

export type ChatCustomSamplePromptRow = z.infer<typeof rowSchema>

/**
 * 保存済みカスタムサンプルを読む。未設定・不正時は空配列。
 */
export function readStoredChatCustomSamplePrompts(): ChatCustomSamplePromptRow[] {
  if (typeof localStorage === 'undefined') {
    return []
  }
  const raw = localStorage.getItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)
  if (raw === null) {
    return []
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw) as unknown
  } catch {
    return []
  }
  const out = arraySchema.safeParse(parsed)
  return out.success ? out.data : []
}

/**
 * カスタムサンプル配列を保存する（Zod で検証してから JSON 化）。
 */
export function writeStoredChatCustomSamplePrompts(rows: ChatCustomSamplePromptRow[]): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  const v = arraySchema.parse(rows)
  localStorage.setItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY, JSON.stringify(v))
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/preferences/chatCustomSamplePromptsStorage.ts frontend/src/preferences/chatCustomSamplePromptsStorage.test.ts && git commit -m "feat(prefs): persist chat custom sample prompts in localStorage"
```

---

### Task 6: Context + Provider + hook

**Files:**
- 新規: [`frontend/src/preferences/chatCustomSamplePromptsContext.tsx`](../../frontend/src/preferences/chatCustomSamplePromptsContext.tsx)
- 新規: [`frontend/src/preferences/useChatCustomSamplePrompts.ts`](../../frontend/src/preferences/useChatCustomSamplePrompts.ts)
- 新規: [`frontend/src/preferences/ChatCustomSamplePromptsProvider.tsx`](../../frontend/src/preferences/ChatCustomSamplePromptsProvider.tsx)
- 新規: [`frontend/src/preferences/ChatCustomSamplePromptsProvider.test.tsx`](../../frontend/src/preferences/ChatCustomSamplePromptsProvider.test.tsx)（任意だが推奨）

**Context の形:**

```typescript
export type ChatCustomSamplePromptsContextValue = {
  readonly customSamplePrompts: readonly ChatCustomSamplePromptRow[]
  readonly setCustomSamplePrompts: (rows: ChatCustomSamplePromptRow[]) => void
  /** チャット表示用: 既定 + カスタム（カスタムは storage 型と同一形状でよい） */
  readonly allSamplePromptsForChat: readonly ChatSamplePromptRow[]
}
```

`allSamplePromptsForChat` は `useMemo(() => [...DEFAULT_CHAT_SAMPLE_PROMPTS, ...customSamplePrompts], [customSamplePrompts])`。**チャットで見せるのは `label`・`text` が非空の行のみ**にフィルタするなら、Provider 内で `filter` するか `ChatPanel` 側で行う。計画では **Provider が `visibleSamplePromptsForChat` を返す**形でもよい（名前は実装で 1 つに統一）。

- [ ] **Step 1: Provider のテスト（RED）**

`customSamplePrompts` の初期値が `readStoredChatCustomSamplePrompts()` と一致し、`setCustomSamplePrompts` で localStorage が更新されることを子コンポーネント経由で検証する。

- [ ] **Step 2: GREEN — 3 ファイル実装**

`SummaryTopNotableMinScoreProvider` をテンプレに、マウント時 `useState(readStored...)`、`setCustomSamplePrompts` で `writeStored...`。

- [ ] **Step 3: `ChatPanel.test.tsx` の `renderChat` を Provider で包む**

```typescript
import { ChatCustomSamplePromptsProvider } from '../../preferences/ChatCustomSamplePromptsProvider'

function renderChat(onError: (e: string | null) => void = vi.fn()) {
  return render(
    <TimeZoneProvider>
      <ChatCustomSamplePromptsProvider>
        <ChatPanel onError={onError} />
      </ChatCustomSamplePromptsProvider>
    </TimeZoneProvider>,
  )
}
```

- [ ] **Step 4: `ChatPanel` が `useChatCustomSamplePrompts` の一覧を使う**

`DEFAULT_CHAT_SAMPLE_PROMPTS` 直参照をやめ、hook の一覧でチップを描画。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/preferences/chatCustomSamplePromptsContext.tsx frontend/src/preferences/useChatCustomSamplePrompts.ts frontend/src/preferences/ChatCustomSamplePromptsProvider.tsx frontend/src/preferences/ChatCustomSamplePromptsProvider.test.tsx frontend/src/panels/chat/ChatPanel.tsx frontend/src/panels/chat/ChatPanel.test.tsx && git commit -m "feat(chat): load sample prompts from custom prompts provider"
```

---

### Task 7: 設定パネル `ChatCustomSamplePromptsPanel`

**Files:**
- 新規: [`frontend/src/panels/settings/ChatCustomSamplePromptsPanel.tsx`](../../frontend/src/panels/settings/ChatCustomSamplePromptsPanel.tsx)
- 新規: [`frontend/src/panels/settings/ChatCustomSamplePromptsPanel.test.tsx`](../../frontend/src/panels/settings/ChatCustomSamplePromptsPanel.test.tsx)

**UI 仕様:**

- 見出し・`hint`: カスタムサンプルはこのブラウザに保存、チャットの既定サンプルに続けて表示される旨。
- **追加**: `crypto.randomUUID()` で `id` を採番し、`{ id, label: '新しいサンプル', text: '' }` を配列末尾に（**空 text はストレージに書かない**か、**書くがチャットでは非表示** — 後者はフィルタで統一）。YAGNI のため **「追加」時点ではローカル state のみに載せ、text と label が非空になったら `setCustomSamplePrompts`」** は複雑なので、**追加行は `label`・`text` にプレースホルダー文字列を入れて即保存**する方が単純。例: `label: '新しいサンプル'`, `text: 'ここに質問文を入力してください'` を初期値とし、ユーザーが編集したら都度 `writeStored`。
- **削除**: 行ごとボタンでその `id` を除外して `setCustomSamplePrompts`。
- **編集**: `input` / `textarea` の `onChange` でコピー更新し、毎回 `setCustomSamplePrompts` + ストレージ（`SummaryTopNotable` と同様の即時永続）。

- [ ] **Step 1: RED — パネルテスト**

レンダー後「追加」で行が増え、localStorage に配列が保存されることを検証（`CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY` を読む）。

- [ ] **Step 2: GREEN — パネル実装**

- [ ] **Step 3: Commit**

```bash
git add frontend/src/panels/settings/ChatCustomSamplePromptsPanel.tsx frontend/src/panels/settings/ChatCustomSamplePromptsPanel.test.tsx && git commit -m "feat(settings): edit chat custom sample prompts"
```

---

### Task 8: `App` への Provider・サブタブ・アイコン・設定テスト更新

**Files:**
- 変更: [`frontend/src/App.tsx`](../../frontend/src/App.tsx)
- 変更: [`frontend/src/components/settings-subtab-icons.tsx`](../../frontend/src/components/settings-subtab-icons.tsx)
- 変更: [`frontend/src/App.settings-subtabs.test.tsx`](../../frontend/src/App.settings-subtabs.test.tsx)

- [ ] **Step 1: `App.tsx`**

`ChatCustomSamplePromptsProvider` を `TimeZoneProvider` 直下など、**`ChatPanel` と設定パネルの両方が子になる**位置に挿入（既存の `AutoRefreshPreferencesProvider` 兄弟でよい）。

設定サブタブに `chat_custom_samples`（型名は snake と camel どちらか **既存 `SettingsSubTabId` に合わせる** — 現状は snake: `score_rules`）→ 例: **`chat_samples`**。

`settingsSubTab === 'chat_samples' && <ChatCustomSamplePromptsPanel />`。

- [ ] **Step 2: `settings-subtab-icons.tsx`**

`SettingsSubTabId` に `'chat_samples'` を追加。`case 'chat_samples':` で吹き出し風の簡易 SVG（`TabButtonSvgIcon` 内に `path` / `rect` 数個）。

- [ ] **Step 3: RED — `App.settings-subtabs.test.tsx`**

`SETTINGS_SUBTAB_LABELS` を `['一般', 'vCenter', 'スコアルール', 'イベント種別ガイド', 'チャットサンプル']` に更新。`it.each` が通ること。

- [ ] **Step 4: GREEN**

- [ ] **Step 5: フロント全体**

```bash
cd /Users/moriyama/git/vcenter-event-assistant/frontend && npm run test -- --run && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/settings-subtab-icons.tsx frontend/src/App.settings-subtabs.test.tsx && git commit -m "feat(app): chat samples settings subtab and provider wiring"
```

---

## セルフレビュー（計画書）

1. **Spec カバレッジ:** 複数選択・定義順連結・`\n\n`・末尾追記・挿入後クリア・loading 時 disabled・カスタム永続化・設定 UI・チャット反映 — 各 Task に対応あり。
2. **プレースホルダ:** 意図的に未記載の箇所なし。Task 7 の初期値は具体例を記載済み。
3. **型一貫性:** `ChatSamplePromptRow`（チャット表示）と `ChatCustomSamplePromptRow`（ストレージ）は同一形状でよい。Provider でマージする際は `readonly` 配列で統一。

---

## 実行の振り先

**計画は保存済み:** [`docs/superpowers/plans/2026-04-04-chat-sample-prompts.md`](./2026-04-04-chat-sample-prompts.md)

**実行オプション:**

1. **Subagent-Driven（推奨）** — タスクごとに新しいサブエージェントをdispatchし、タスク間でレビューする。
2. **Inline Execution** — このセッションで `executing-plans` に沿ってチェックポイント付きで一括実行する。

どちらで進めますか。
