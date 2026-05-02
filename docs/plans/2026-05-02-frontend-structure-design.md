# フロントエンド構造改善 — 設計ドキュメント

**日付:** 2026-05-02
**目的:** App.tsx にハードコードされているタブ（メインタブ・設定サブタブ）のレンダリングをデータ駆動化し、コードの記述量を削減するとともに、将来のタブ追加や並び替えを容易にする。

## 背景

「3. フロントエンドの構造改善」のうち、以下2点は先行するリファクタリング（タスク：巨大ファイルの分割）にて既に完了しています。
1. **単一 `App.css` のコンポーネント別分割**（完了済み）
2. **`App.tsx` の Provider 構成整理**（`AppProviders.tsx` への抽出、完了済み）

本設計では、残る **「タブレンダリングのデータ駆動化」** に焦点を当てます。

現在、`App.tsx` 内の `<nav className="tabs">` および `<nav className="settings-subtabs">` において、すべてのタブボタンが個別にハードコードされており、同一の構造が繰り返し記述されています（約100行のボイラープレートコード）。

## 設計方針

### 1. タブ定義オブジェクトの導入
各タブの識別子（`id`）と表示名（`label`）を対応づける定数配列を定義します。

```tsx
type TabConfig = { id: MainTabId; label: string }
const MAIN_TABS: TabConfig[] = [
  { id: 'summary', label: '概要' },
  { id: 'events', label: 'イベント' },
  // ...
]

type SubTabConfig = { id: SettingsSubTabId; label: string }
const SETTINGS_SUBTABS: SubTabConfig[] = [
  { id: 'general', label: '一般' },
  { id: 'vcenters', label: 'vCenter' },
  // ...
]
```

### 2. コンポーネントのループ展開
`MAIN_TABS` および `SETTINGS_SUBTABS` を `.map()` で回し、ナビゲーション用の `<button>` 要素を動的に生成します。これにより：
- コードの重複を排除し、`App.tsx` を大幅に短縮します。
- `tab` や `settingsSubTab` ステートの切り替え、`setShowHelp(false)`、`setErr(null)` のリセット処理もループ内で一元化できます。

### 3. スコープ
本タスクでは「ナビゲーションボタン部分」のデータ駆動化を対象とします。メインコンテンツのレンダリング部（`<SummaryPanel />` などの呼び出し）については、コンポーネントごとの Props が異なる（`retention` など）ため、可読性重視で現在のインライン条件付きレンダリング（`{tab === '...' && <Component />}`）を維持します。
