# 簡易ヘルプ機能 実装プラン (TDD対応版)

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** アプリケーションタイトル下部に開閉可能なヘルプエリアを追加し、各画面の操作ガイドを表示する。TDD（テスト駆動開発）を必須とし、まずテストから作成する。

**Architecture:** `App.tsx` で集中管理するステート (`showHelp`) と定数 (`HELP_CONTENT`) を使用し、タブ切り替え時に自動的に閉じるようにする。

**Tech Stack:** React, TypeScript, Vitest, Testing Library, CSS (Vanilla)

---

### Task 1: 失敗するテストの作成 (TDD)

**Files:**
- Create: `frontend/src/App.help.test.tsx`

**Step 1: Write initial tests**
ヘルプボタンの存在、初期状態の非表示、クリックでの表示、タブ切り替えでの非表示を検証するテストを記述する。

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import App from './App'

describe('App 簡易ヘルプ機能', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ event_retention_days: 7, metric_retention_days: 7 })
    }))
  })

  it('「使い方を表示」ボタンが表示されている', async () => {
    render(<App />)
    const button = await screen.findByRole('button', { name: /使い方を表示/ })
    expect(button).toBeInTheDocument()
  })

  it('初期状態ではヘルプエリアが表示されていない', async () => {
    render(<App />)
    expect(screen.queryByText(/【概要】/)).not.toBeInTheDocument()
  })

  it('ボタンクリックでヘルプエリアが表示される', async () => {
    render(<App />)
    const button = await screen.findByRole('button', { name: /使い方を表示/ })
    fireEvent.click(button)
    expect(screen.getByText(/【概要】/)).toBeInTheDocument()
  })

  it('タブを切り替えた際にヘルプエリアが自動的に閉じる', async () => {
    render(<App />)
    const helpBtn = await screen.findByRole('button', { name: /使い方を表示/ })
    fireEvent.click(helpBtn)
    expect(screen.getByText(/【概要】/)).toBeInTheDocument()

    // イベントタブに切り替え
    const eventTab = screen.getByRole('button', { name: 'イベント' })
    fireEvent.click(eventTab)

    // ヘルプが閉じていることを確認
    await waitFor(() => {
      expect(screen.queryByText(/【概要】/)).not.toBeInTheDocument()
    })
  })
})
```

**Step 2: Run tests to verify they fail**
Run: `npm test frontend/src/App.help.test.tsx`
Expected: FAIL (ボタンが見つからない、またはテキストが見つからない)

**Step 3: Commit**

```bash
git add frontend/src/App.help.test.tsx
git commit -m "test: add failing tests for simple help function"
```

### Task 2: ヘルプアイコンとスタイルの作成

**Files:**
- Create: `frontend/src/components/help-icon.tsx`
- Modify: `frontend/src/App.css`

**Step 1: Create HelpIcon**
シンプルな SVG アイコンを作成する。

**Step 2: Add CSS**
ヘルプエリア、トグルボタンのスタイルを追加する。

**Step 3: Commit**

```bash
git add frontend/src/components/help-icon.tsx frontend/src/App.css
git commit -m "feat: add HelpIcon and basic styles"
```

### Task 3: App.tsx へのロジック実装とテストパス

**Files:**
- Modify: `frontend/src/App.tsx`

**Step 1: Define HELP_CONTENT and State**
ヘルプ文言を定義し、`showHelp` ステートを追加。

**Step 2: Implement Toggle and Reset Logic**
ボタンクリックでのトグル、タブ切り替え時のリセットを実装する。

**Step 3: Run tests to verify they pass**
Run: `npm test frontend/src/App.help.test.tsx`
Expected: PASS

**Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: implement help section logic and UI"
```

### Task 4: 動作確認とリファクタリング

**Step 1: Manual Verification**
ブラウザで実際の挙動を確認する。

**Step 2: Final Commit**

```bash
git commit --allow-empty -m "docs: complete help function implementation with TDD"
```
