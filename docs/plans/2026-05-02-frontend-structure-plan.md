# フロントエンドの構造改善 Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** App.tsx のタブレンダリングをデータ駆動化し、ハードコードされたボイラープレートを削減する。

**Architecture:** `App.css` のコンポーネント別分割および `App.tsx` の Provider 構成整理（AppProviders の導入）は既に完了済みです。本計画では、メインタブと設定サブタブのナビゲーションボタンを配列からの `map` 展開へとリファクタリングします。

**Tech Stack:** React, TypeScript

---

### Task 1: メインタブのデータ駆動化

**Files:**
- Modify: `frontend/src/App.tsx:40-150`

**Step 1: タブ定義配列の作成**

`App.tsx` のコンポーネント外（`type Tab = ...` の下あたり）に `MAIN_TABS` を定義します。

```tsx
type TabConfig = { id: Tab; label: string }

const MAIN_TABS: TabConfig[] = [
  { id: 'summary', label: '概要' },
  { id: 'events', label: 'イベント' },
  { id: 'metrics', label: 'グラフ' },
  { id: 'digests', label: 'ダイジェスト' },
  { id: 'alerts', label: '通知履歴' },
  { id: 'chat', label: 'チャット' },
  { id: 'settings', label: '設定' },
]
```

**Step 2: `<nav className="tabs">` のループ化**

`App.tsx` 内の `<nav className="tabs">` を以下のように修正します。

```tsx
        <nav className="tabs">
          {MAIN_TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? 'active' : undefined}
              onClick={() => {
                setTab(t.id)
                setShowHelp(false)
                setErr(null)
              }}
            >
              <span className="tab-button__inner">
                <MainTabIcon tabId={t.id} />
                <span className="tab-button__label">{t.label}</span>
              </span>
            </button>
          ))}
        </nav>
```

**Step 3: ビルド検証とコミット**

Run: `cd frontend && npm run build`
Expected: ビルドがエラーなく成功すること

```bash
git add frontend/src/App.tsx
git commit -m "refactor: data-driven main tabs rendering"
```

---

### Task 2: 設定サブタブのデータ駆動化

**Files:**
- Modify: `frontend/src/App.tsx:50-200`

**Step 1: サブタブ定義配列の作成**

`App.tsx` のコンポーネント外（`MAIN_TABS` の下あたり）に `SETTINGS_SUBTABS` を定義します。

```tsx
type SubTabConfig = { id: SettingsSubTab; label: string }

const SETTINGS_SUBTABS: SubTabConfig[] = [
  { id: 'general', label: '一般' },
  { id: 'vcenters', label: 'vCenter' },
  { id: 'score_rules', label: 'スコアルール' },
  { id: 'event_type_guides', label: 'イベント種別ガイド' },
  { id: 'alerts', label: 'アラート' },
  { id: 'chat_samples', label: 'チャット' },
]
```

**Step 2: `<nav className="settings-subtabs">` のループ化**

`App.tsx` 内の `<nav className="settings-subtabs" aria-label="設定">` を以下のように修正します。

```tsx
            <nav className="settings-subtabs" aria-label="設定">
              {SETTINGS_SUBTABS.map((sub) => (
                <button
                  key={sub.id}
                  type="button"
                  className={settingsSubTab === sub.id ? 'active' : undefined}
                  aria-selected={settingsSubTab === sub.id}
                  onClick={() => {
                    setSettingsSubTab(sub.id)
                    setShowHelp(false)
                    setErr(null)
                  }}
                >
                  <span className="tab-button__inner">
                    <SettingsSubTabIcon tabId={sub.id} />
                    <span className="tab-button__label">{sub.label}</span>
                  </span>
                </button>
              ))}
            </nav>
```

**Step 3: 最終検証とコミット**

Run: `cd frontend && npm run build`
Expected: ビルドがエラーなく成功すること

```bash
git add frontend/src/App.tsx
git commit -m "refactor: data-driven settings subtabs rendering"
```
