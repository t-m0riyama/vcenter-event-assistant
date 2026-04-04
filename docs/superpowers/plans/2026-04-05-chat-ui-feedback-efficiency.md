# チャット UI 送信中フィードバック・操作効率 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **TDD は省略不可:** 振る舞いを変える本番コードは、**対応する失敗テスト（Red）を先に用意し、FAIL を確認してから**最小実装へ進む。テストだけ後追いで「合わせる」ことは本計画では認めない。併用推奨: superpowers:test-driven-development。

**Goal:** チャットパネルに送信中の視覚・ARIA フィードバック（B）と、Enter 送信・会話クリア・最新回答コピー（C）を追加する。

**Architecture（振る舞い優先・具体 DOM はサードパーティ方針で選択）:** 会話データは既存の `messages: ChatMessage[]` のまま。送信中の仮 UI は **`loading` に連動したリスト末尾のプレースホルダ**（`li` 自前でも、UI プリミティブでも可）。最下部付近でのみ新着追従するスクロールは **自前 `useLayoutEffect` + [chatMessagesListScroll.ts](frontend/src/panels/chat/chatMessagesListScroll.ts) でも、専用フック／ライブラリでも可**。キーボード送信は **Enter / Shift+Enter、IME 中は送信しない**。会話クリアは **`window.confirm` でも、Radix 等の AlertDialog でも可**（後者は依存とスタイル調整が必要）。コピーは `navigator.clipboard.writeText` を基本とする。

**Tech Stack（ベース）:** React 19、TypeScript、Vite、Vitest、`@testing-library/react`、既存 [ChatPanel.tsx](frontend/src/panels/chat/ChatPanel.tsx)、スタイル [App.css](frontend/src/App.css)。**B・C（Task 1〜5）では会話バブルはプレーン表示のまま。** **フェーズ A** でチャットに GFM（`react-markdown` + `remark-gfm`）を適用する。**B・C・A で追加する npm のうち未導入分は「実装方式の再検討（B+C+A・サードパーティ）」で束として決める。**

## TDD ポリシー（必須）

- **順序:** 各 Task（および **フェーズ A**）で振る舞いを変えるときは **Red → Green → Refactor**。先に **失敗するテスト**を書き、`vitest` で FAIL を確認してから最小実装で Green にする。
- **禁止:** 本番コード（`ChatPanel.tsx` 等）だけ先に完成させ、後からテストを都合よく足す・直すだけにすること。
- **境界:** `fetch` / `window.confirm` / `clipboard` 等はモックでよい。**ユーザーから観測可能な結果**（DOM、ARIA、`scrollTop`、POST の有無・本文）はテストで固定する。
- **Task 2:** 新機能追加は行わない。全テスト PASS ならコミット不要。FAIL がある場合は **テスト期待の更新または新規 `it` を先に**置き、実装変更は最小限にとどめる。
- **完了条件:** 当該 Task（またはフェーズ A の各ステップ）のコミット時点で、関連スイートおよび `cd frontend && npm run test` が Green。必要に応じて `npm run lint`。

**前提（2026-04 更新）:**

1. **B+C の途中実装は採用しない**（例: `feat/chat-ui-feedback-efficiency` 上の変更は **マージせず破棄**し、`main` を基準に再実装する。Git の削除・ブランチ整理は実装担当が実行）。
2. **フェーズ A（Markdown・GFM 含む）は本ファイルの Task 1〜5 の範囲外**だが、**チャットでの GFM 対応はフェーズ A の必須項目**として下記「フェーズ A（Markdown・GFM）」に従う。sanitize / コードハイライト等の追加 npm は同ロードマップで選定し、別計画へ写してもよい。
3. **フェーズ A の実装も上記 TDD ポリシーに従う**（テスト先行を省略しない）。
4. `main` 直コミットは避け、新規 feature ブランチで作業する。

---

## ファイル構成（変更・新規）

| ファイル | 役割 |
|----------|------|
| [frontend/src/panels/chat/ChatPanel.tsx](frontend/src/panels/chat/ChatPanel.tsx) | `loading` 時プレースホルダ行、`aria-busy`、キーボード送信、クリア・コピー UI とハンドラ、`useLayoutEffect` 依存拡張 |
| [frontend/src/panels/chat/ChatPanel.test.tsx](frontend/src/panels/chat/ChatPanel.test.tsx) | 上記の振る舞いの結合テスト（TDD の主戦場） |
| [frontend/src/App.css](frontend/src/App.css) | プレースホルダ行・ツールバーボタン用の最小スタイル（既存トークンに合わせる） |
| （フェーズ A 想定）`frontend/src/panels/chat/ChatMarkdownContent.tsx` 等 | `react-markdown` + `remark-gfm` をバブル用に閉じる薄いラッパ（**Task 1〜5 完了後**） |

**分割の判断:** キーボード判定を `chatComposerKeydown.ts` などに切り出すのは **100 行未満で済むなら ChatPanel 内に留めてよい**。切り出す場合は **純関数のみ**とし、[chatMessagesListScroll.test.ts](frontend/src/panels/chat/chatMessagesListScroll.test.ts) と同様に単体テストファイルを追加する（その場合も **先にテスト**）。

**サードパーティ採用時:** 例として `MarkdownMessageBubble.tsx`（`react-markdown` + plugins）、`ChatComposer.tsx`（`react-textarea-autosize` ラップ）など **薄いラッパファイル**を増やして [ChatPanel.tsx](frontend/src/panels/chat/ChatPanel.tsx) を薄くする選択可。具体パスは選定した束（S0〜S3）に合わせて計画実行時に確定する。

---

### Task 1: 送信中プレースホルダ行と `aria-busy`

**Files:**

- Modify: `frontend/src/panels/chat/ChatPanel.tsx`（`ul` 子の描画、`useLayoutEffect` の依存配列）
- Modify: `frontend/src/App.css`（プレースホルダ用クラス）
- Test: `frontend/src/panels/chat/ChatPanel.test.tsx`

- [ ] **Step 1: 失敗するテストを書く（TDD）**

`POST /api/chat` の Promise を **手動で解決するまで未完了**にし、`loading === true` の間だけプレースホルダが見えることを検証する。

```typescript
it('送信中は会話リストにプレースホルダが表示され ul に aria-busy が付く', async () => {
  let resolveChat!: (r: Response) => void
  const chatPromise = new Promise<Response>((res) => {
    resolveChat = res
  })

  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/vcenters')) {
      return Promise.resolve(jsonResponse([]))
    }
    if (url.endsWith('/api/chat') && init?.method === 'POST') {
      return chatPromise
    }
    return Promise.resolve(new Response('not found', { status: 404 }))
  })
  vi.stubGlobal('fetch', fetchMock)

  renderChat()
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalled()
  })

  fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
    target: { value: '保留テスト' },
  })
  fireEvent.click(screen.getByRole('button', { name: '送信' }))

  await waitFor(() => {
    expect(screen.getByText('応答を生成しています…')).toBeInTheDocument()
  })
  expect(messagesListElement()).toHaveAttribute('aria-busy', 'true')

  resolveChat(jsonResponse({ assistant_content: '完了', error: null }))

  await waitFor(() => {
    expect(screen.queryByText('応答を生成しています…')).not.toBeInTheDocument()
  })
  expect(messagesListElement()).toHaveAttribute('aria-busy', 'false')
})
```

※ 上記の文言・`aria-busy` の付け方は実装で一致させる。**この時点では実装が無いためテストは FAIL** すること。

- [ ] **Step 2: テストを実行して失敗を確認**

Run:

```bash
cd frontend && npx vitest run src/panels/chat/ChatPanel.test.tsx -t "送信中は会話リストにプレースホルダ"
```

Expected: **1 failed**（プレースホルダまたは `aria-busy` が見つからない）。

- [ ] **Step 3: 最小実装**

- `loading` が `true` のとき、`messages.map` の **後**に `li` を 1 つ描画（クラス例: `chat-panel__msg chat-panel__msg--pending`）。中身は `span.chat-panel__role` + プレースホルダ文言「応答を生成しています…」。
- `ul` に `aria-busy={loading ? 'true' : 'false'}` を付与。
- `useLayoutEffect`（[ChatPanel.tsx 59–79 行付近](frontend/src/panels/chat/ChatPanel.tsx)）の依存配列に `loading` を追加。`stickToBottomRef.current === true` かつ `loading === true` のときは **リスト最下端**へ `scrollTop` を設定（プレースホルダが見えるように）。既存の「最終メッセージが assistant」の分岐は `loading` が false のときのみ適用するなど、プレースホルダ表示中は下端寄せを優先。

- [ ] **Step 4: テストを再実行して成功を確認**

Run:

```bash
cd frontend && npx vitest run src/panels/chat/ChatPanel.test.tsx -t "送信中は会話リストにプレースホルダ"
```

Expected: **PASS**。

- [ ] **Step 5: 回帰確認**

Run:

```bash
cd frontend && npm run test
```

Expected: **全件 PASS**。

- [ ] **Step 6: コミット**

```bash
git add frontend/src/panels/chat/ChatPanel.tsx frontend/src/App.css frontend/src/panels/chat/ChatPanel.test.tsx
git commit -m "feat(chat): show loading placeholder and aria-busy on message list"
```

---

### Task 2: 追従スクロール既存テストとの整合

**Files:**

- Modify: `frontend/src/panels/chat/ChatPanel.test.tsx`（必要なら期待値の調整のみ）
- Modify: `frontend/src/panels/chat/ChatPanel.tsx`（スクロール条件の微調整）

- [ ] **Step 1: 全テスト実行**

Run: `cd frontend && npm run test`

- [ ] **Step 2: 結果の分岐**

- **すべて PASS** → Task 1 の実装で十分なため、本タスクのコミットは不要。チェックボックスを完了扱いにして次へ。
- **FAIL がある** → 次の Step 3 へ。

- [ ] **Step 3: Red → Green（TDD）**

例: プレースホルダ表示で `scrollHeight` が変わり、既存の「最下部付近」テストのタイミングがずれる場合は、**先に** 該当 `it` を修正するテストを書き直す（プレースホルダ消滅を `waitFor` で待ってから `scrollTop` を検証する等）。実装側の `useLayoutEffect` は **過剰に変えない**。

- [ ] **Step 4: コミット（Step 3 を実施した場合のみ）**

```bash
git add frontend/src/panels/chat/ChatPanel.tsx frontend/src/panels/chat/ChatPanel.test.tsx
git commit -m "test(chat): align scroll tests with loading placeholder"
```

---

### Task 3: Enter で送信、Shift+Enter で改行

**Files:**

- Modify: `frontend/src/panels/chat/ChatPanel.tsx`（`textarea` の `onKeyDown`）
- Test: `frontend/src/panels/chat/ChatPanel.test.tsx`

- [ ] **Step 1: 失敗するテストを書く**

```typescript
it('Enter キーで送信される', async () => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/vcenters')) {
      return Promise.resolve(jsonResponse([]))
    }
    if (url.endsWith('/api/chat') && init?.method === 'POST') {
      return Promise.resolve(jsonResponse({ assistant_content: 'ok', error: null }))
    }
    return Promise.resolve(new Response('not found', { status: 404 }))
  })
  vi.stubGlobal('fetch', fetchMock)

  renderChat()
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalled()
  })

  const ta = screen.getByPlaceholderText('質問を入力…')
  fireEvent.change(ta, { target: { value: 'enter で送る' } })
  fireEvent.keyDown(ta, { key: 'Enter', code: 'Enter', shiftKey: false })

  await waitFor(() => {
    expect(screen.getByText('ok')).toBeInTheDocument()
  })
})

it('Shift+Enter では送信せず改行だけされる', async () => {
  const fetchMock = vi.fn(() => Promise.resolve(jsonResponse([])))
  vi.stubGlobal('fetch', fetchMock)

  renderChat()
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalled()
  })

  const ta = screen.getByPlaceholderText('質問を入力…') as HTMLTextAreaElement
  fireEvent.change(ta, { target: { value: 'line1' } })
  fireEvent.keyDown(ta, { key: 'Enter', code: 'Enter', shiftKey: true })

  const posts = fetchMock.mock.calls.filter(
    (c) => String(c[0]).endsWith('/api/chat') && (c[1] as RequestInit)?.method === 'POST',
  )
  expect(posts.length).toBe(0)
  expect(ta.value).toContain('\n')
})
```

※ 2 つ目のテストは、実装で `preventDefault` 後に `setDraft` で `\n` を挿入する形に合わせる。**実装前は 2 つ目が FAIL**（改行が入らない／または送信される）することを確認する。

- [ ] **Step 2: 失敗確認**

Run:

```bash
cd frontend && npx vitest run src/panels/chat/ChatPanel.test.tsx -t "Enter キー"
```

```bash
cd frontend && npx vitest run src/panels/chat/ChatPanel.test.tsx -t "Shift\\+Enter"
```

- [ ] **Step 3: 実装**

- `onKeyDown`: `e.nativeEvent.isComposing === true` なら return。
- `e.key === 'Enter' && !e.shiftKey`: `e.preventDefault()`、`void send()`（`send` は既存 `useCallback`）。
- `e.key === 'Enter' && e.shiftKey`: `e.preventDefault()`、`setDraft((d) => d + '\n')`（またはキャレット位置挿入。YAGNI なら末尾追記で可）。

- [ ] **Step 4: Green 確認**

Run: `cd frontend && npx vitest run src/panels/chat/ChatPanel.test.tsx -t "Enter"`

- [ ] **Step 5: コミット**

```bash
git add frontend/src/panels/chat/ChatPanel.tsx frontend/src/panels/chat/ChatPanel.test.tsx
git commit -m "feat(chat): enter to send and shift+enter for newline"
```

---

### Task 4: 会話クリア（確認ダイアログ付き）

**Files:**

- Modify: `frontend/src/panels/chat/ChatPanel.tsx`
- Modify: `frontend/src/App.css`（ボタン配置が崩れない程度の最小）
- Test: `frontend/src/panels/chat/ChatPanel.test.tsx`

- [ ] **Step 1: 失敗するテストを書く**

```typescript
it('会話をクリアで確認後にメッセージが空になる', async () => {
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/vcenters')) {
      return Promise.resolve(jsonResponse([]))
    }
    if (url.endsWith('/api/chat') && init?.method === 'POST') {
      return Promise.resolve(jsonResponse({ assistant_content: 'a', error: null }))
    }
    return Promise.resolve(new Response('not found', { status: 404 }))
  })
  vi.stubGlobal('fetch', fetchMock)

  renderChat()
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalled()
  })

  fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
    target: { value: 'q' },
  })
  fireEvent.click(screen.getByRole('button', { name: '送信' }))
  await waitFor(() => {
    expect(screen.getByText('a')).toBeInTheDocument()
  })

  fireEvent.click(screen.getByRole('button', { name: '会話をクリア' }))

  expect(confirmSpy).toHaveBeenCalled()
  expect(screen.queryByText('a')).not.toBeInTheDocument()
  expect(screen.queryByText('q')).not.toBeInTheDocument()

  confirmSpy.mockRestore()
})
```

- [ ] **Step 2: 失敗確認**

Run:

```bash
cd frontend && npx vitest run src/panels/chat/ChatPanel.test.tsx -t "会話をクリア"
```

Expected: **FAIL**（ボタンなし）。

- [ ] **Step 3: 実装**

- `ul` の直前またはコンポーザ直上に `button type="button"`「会話をクリア」、`disabled={loading || messages.length === 0}`。
- クリック時: `if (!window.confirm('会話をすべて削除しますか？')) return`（文言はプロダクトに合わせてよいがテストでは `confirm` が呼ばれたことのみ検証してよい）。
- `setMessages([])`、`setLastLlmContext(null)`（会話と無関係なメタを残すかは要件次第。**空に揃える**のが自然）。

- [ ] **Step 4: Green**

Run: `cd frontend && npx vitest run src/panels/chat/ChatPanel.test.tsx -t "会話をクリア"`

- [ ] **Step 5: コミット**

```bash
git add frontend/src/panels/chat/ChatPanel.tsx frontend/src/App.css frontend/src/panels/chat/ChatPanel.test.tsx
git commit -m "feat(chat): clear conversation with confirm"
```

---

### Task 5: 最新のアシスタント回答をコピー

**Files:**

- Modify: `frontend/src/panels/chat/ChatPanel.tsx`
- Test: `frontend/src/panels/chat/ChatPanel.test.tsx`

- [ ] **Step 1: 失敗するテストを書く**

```typescript
it('最新の回答をコピーでクリップボードに最終アシスタント本文が入る', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', {
    ...navigator,
    clipboard: { writeText },
  })

  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/vcenters')) {
      return Promise.resolve(jsonResponse([]))
    }
    if (url.endsWith('/api/chat') && init?.method === 'POST') {
      return Promise.resolve(jsonResponse({ assistant_content: '最終回答', error: null }))
    }
    return Promise.resolve(new Response('not found', { status: 404 }))
  })
  vi.stubGlobal('fetch', fetchMock)

  renderChat()
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalled()
  })

  fireEvent.change(screen.getByPlaceholderText('質問を入力…'), {
    target: { value: 'q' },
  })
  fireEvent.click(screen.getByRole('button', { name: '送信' }))
  await waitFor(() => {
    expect(screen.getByText('最終回答')).toBeInTheDocument()
  })

  fireEvent.click(screen.getByRole('button', { name: '最新の回答をコピー' }))

  await waitFor(() => {
    expect(writeText).toHaveBeenCalledWith('最終回答')
  })
})
```

- [ ] **Step 2: 失敗確認**

Run:

```bash
cd frontend && npx vitest run src/panels/chat/ChatPanel.test.tsx -t "最新の回答をコピー"
```

- [ ] **Step 3: 実装**

- ボタン「最新の回答をコピー」: `disabled` は **最終 `messages` が assistant でない**、または `loading`、または `messages.length === 0`。
- クリック: 最後から辿って `role === 'assistant'` の `content` を取得し `await navigator.clipboard.writeText(...)`。失敗時は `onError` にメッセージ（既存 `toErrorMessage` パターンに合わせる）。

- [ ] **Step 4: Green**

Run: `cd frontend && npx vitest run src/panels/chat/ChatPanel.test.tsx -t "最新の回答をコピー"`

- [ ] **Step 5: 全体テストと lint**

Run:

```bash
cd frontend && npm run test && npm run lint
```

- [ ] **Step 6: コミット**

```bash
git add frontend/src/panels/chat/ChatPanel.tsx frontend/src/panels/chat/ChatPanel.test.tsx
git commit -m "feat(chat): copy latest assistant reply to clipboard"
```

---

## フェーズ A（Markdown・GFM）

**位置づけ:** 本ファイルの **Task 1〜5**（B+C）**完了後**に実施。Task 1〜5 の間は会話バブル **プレーンテキストのまま**とする。

**必須成果:** **チャット**のユーザー／アシスタント本文に **GitHub Flavored Markdown（GFM）** を適用する。既存依存の **`react-markdown`** と **`remark-gfm`** を使い、[DigestsPanel.tsx](frontend/src/panels/digests/DigestsPanel.tsx) と同様に `remarkPlugins={[remarkGfm]}` を渡す。表・タスクリスト・打ち消し線等をバブル内で解釈できること。

**スタイル:** 見出し・表・`pre`/`code` をダイジェストと揃えるなら [App.css](frontend/src/App.css) の `.digest-markdown` をチャット側でも共有する（`.chat-panel__bubble` 内の `white-space` は Markdown ブロック向けに調整）。

**TDD（必須）:** 例として、モックの `assistant_content` が GFM 表（`|列|…`）のとき **`role="table"`** やヘッダセルが現れることを検証する `it` を **[ChatPanel.test.tsx](frontend/src/panels/chat/ChatPanel.test.tsx)** に **先に**追加し、プレーンテキスト実装のまま **FAIL** を確認してから、`ReactMarkdown` 導入で **Green** にする。

**推奨構成:** 薄いラッパ（例: `frontend/src/panels/chat/ChatMarkdownContent.tsx`）に `ReactMarkdown` + `remarkGfm` を閉じ、[ChatPanel.tsx](frontend/src/panels/chat/ChatPanel.tsx) の `.chat-panel__bubble` 内で利用。

**拡張（同一ロードマップ）:** XSS 対策の **`rehype-sanitize`**、コードフェンスの **`rehype-highlight` / `lowlight`** は下記「A（次ステップ・Markdown）で使えるモジュール」と束の選定に従い、GFM 導入と同じフェーズまたは直後のタスクで TDD により追加する。

### フェーズ A チェックリスト（例）

- [ ] **A-Red:** GFM 表（等）を検証する結合テストを追加し、現状のプレーンテキスト実装で FAIL を確認する
- [ ] **A-Green:** `react-markdown` + `remark-gfm` をバブルに組み込み、テストを PASS にする
- [ ] **A-Refactor:** ラッパ分割・CSS 整理。`npm run test` / `npm run lint` を維持する

---

## 仕様カバレッジ（セルフレビュー）

| 要件 | タスク |
|------|--------|
| 送信中フィードバック（プレースホルダ） | Task 1 |
| スクリーンリーダ向け busy | Task 1 (`aria-busy`) |
| 追従スクロールとプレースホルダの整合 | Task 1–2 |
| Enter / Shift+Enter | Task 3 |
| 会話クリア + 確認 | Task 4 |
| 最新アシスタント回答のコピー | Task 5 |
| チャットでの GFM（表・タスクリスト等） | **フェーズ A**（Task 1〜5 の外） |
| XSS・コードハイライト（sanitize / highlight） | **フェーズ A 拡張**（モジュール表・束に従う） |

**注:** Task 1〜5 および **フェーズ A** はいずれも **「TDD ポリシー（必須）」** 節に従う。

---

## 実装方式の再検討（B+C+A・サードパーティ全体像・2026-04）

**目的:** 途中の B+C 実装を捨てたうえで、**B（送信中フィードバック）・C（操作効率）・次ステップ A（Markdown 可読性）**を横断的に、npm 活用の有無と束を決める材料とする。

### 既存・制約

- [`frontend/package.json`](frontend/package.json): 既に **`react-markdown` / `remark-gfm`**。A の基盤として流用し、ダイジェスト表示と **同一パイプライン（components / 見出し・コード・リンク）**に寄せるのが望ましい。
- **Tailwind / Radix / shadcn** は未導入。チャットだけに局所導入すると `App.css` トークンと二系統になりやすい。**採用するなら「チャット専用の薄いラッパ」に留めるか、将来アプリ全体の UI 方針とセットで決める。**

### B（送信中）で使えるモジュール

| 手段 | 候補 | 備考 |
|------|------|------|
| プレースホルダ行 | **自前 `li`**、`react-loading-skeleton` | 要件は文言 + `aria-busy` で足りるなら自前が最軽量。スケルトンは見た目の統一コストあり |
| リストの状態通知 | **自前 `aria-busy`**、（将来）Radix の region 系 | 現状は WAI-ARIA 属性で十分なことが多い |
| 追従スクロール | **既存 `chatMessagesListScroll` + `useLayoutEffect`**、`use-stick-to-bottom` 等のコミュニティフック | ライブラリ化する場合は **「アシスタント先頭寄せ」など既存仕様の回帰テスト**をセットで書き換え |

### C（操作効率）で使えるモジュール

| 手段 | 候補 | 備考 |
|------|------|------|
| 入力欄の伸縮 | **`react-textarea-autosize`** | 依存小。Enter/Shift+Enter・IME はアプリ側で維持 |
| 確認ダイアログ | **`window.confirm`**、`@radix-ui/react-alert-dialog` | ゼロ依存 vs a11y・見た目。Radix 採用時は CSS を `App.css` に合わせて足す |
| コピー | **`navigator.clipboard`（標準）** | 特に追加パッケージ不要。失敗時メッセージは既存 `onError` パターン |
| キーバインドのみ切り出し | **`@radix-ui/react-use-controllable-state` は不要**、`tinykeys` 等 | チャット1画面の Enter 送信には過剰になりがち。自前 `onKeyDown` で十分なことが多い |

### A（次ステップ・Markdown）で使えるモジュール（既存 `react-markdown` 前提）

| 手段 | 候補 | 備考 |
|------|------|------|
| GitHub Flavored Markdown | **`remark-gfm`（依存は既存）** | **ダイジェストは [DigestsPanel](frontend/src/panels/digests/DigestsPanel.tsx) で適用済み。チャット会話バブルへの GFM は本ファイルの「フェーズ A（Markdown・GFM）」節で必須実装**（表・タスクリスト等） |
| XSS 対策 | **`rehype-sanitize`**（推奨） | `react-markdown` の `urlTransform` だけでは不足しがち。**許可タグ・スキーマを設計ドキュメント化** |
| コードハイライト | **`rehype-highlight`**、**`@shikijs/rehype`** | Shiki はバンドル大・品質高。後から差し替え可能 |
| 数式 | **`remark-math` + `rehype-katex`** | 運用で数式が要る場合のみ |
| 代替パイプライン | `markdown-to-jsx` | `react-markdown` と二重管理になるため、**ダイジェストと統一できない限り非推奨** |

### 推奨パッケージ「束」（実装再開時に 1 つ選ぶ）

| 束 ID | 内容 | 向き |
|-------|------|------|
| **S0（最小）** | B+C ほぼ自前 + 既存スクロール。A は `react-markdown` + `remark-gfm` + **`rehype-sanitize`** のみ追加 | 依存増を最小化、既存コードとの連続性最大 |
| **S1（コンポーザー強化）** | S0 + **`react-textarea-autosize`** | 入力 UX だけ先に上げる |
| **S2（スクロール委譲）** | S1 + **追従フック系パッケージ**（選定要）。自前 `chatMessagesListScroll` は縮小または廃止 | スクロール仕様のテストをライブラリ前提に書き直すコストあり |
| **S3（ダイアログ a11y）** | S1 または S2 + **Radix AlertDialog**（会話クリアのみでも可） | `App.css` へのモーダル用スタイル追加が必要 |
| **S4（将来・全体 UI）** | Radix + トークン統一で設定・ダイジェストまで含む | **B+C 単体のスコープ外**。別ロードマップ |

**フルチャット UI キット・Stream 等 SaaS バインド SDK** は、自前 `/api/chat`・パネル埋め込みとの相性が悪く、**本ロードマップでは採用しない**（再評価する場合は別検討書）。

### 次のアクション（実装再開前チェックリスト）

1. 上記 **S0〜S3 のどれで行くか**（または S0 から段階導入）を決める。
2. **A 用に `rehype-sanitize` のスキーマ**（許可タグ・属性）を短文で決め、ダイジェスト表示と共通化する方針を書く。
3. 本ファイルの **Task 1〜5** は引き続き **受け入れ条件**として有効。実装手順のコード例は、選んだ束に合わせて **エージェント向けに差し替えてよい**（例: Textarea を `react-textarea-autosize` に）。**TDD 順序（テスト先行）はスキップしない。**
4. Task 1〜5 完了後、**「フェーズ A（Markdown・GFM）」** 節に従いチャットへ GFM を入れる（**TDD 必須**）。
5. Git: **途中 B+C ブランチを破棄**し、`main` から新ブランチで再開する。

## 実行時の引き渡し

**Plan complete and saved to `docs/superpowers/plans/2026-04-05-chat-ui-feedback-efficiency.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — タスクごとに新しいサブエージェントを起動し、タスク間でレビューする。REQUIRED SUB-SKILL: superpowers:subagent-driven-development

**2. Inline Execution** — 同一セッションで executing-plans に沿ってチェックポイント付き実行。REQUIRED SUB-SKILL: superpowers:executing-plans

**TDD:** **「TDD ポリシー（必須）」** 節に従い、**Red 先行を省略しない**。推奨: superpowers:test-driven-development

**Which approach?**
