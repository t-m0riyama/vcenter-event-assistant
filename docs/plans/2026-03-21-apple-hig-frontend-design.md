# Apple HIG 準拠フロントエンドデザイン実装計画

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `docs/design/design-ui-ux.md` のトークン・コンポーネント規約に沿い、[Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/) のトーン（システムフォント、8pt グリッド、44px タッチターゲット、セマンティックカラー、フォーカスリング）に揃えた単一ページ UI にする。

**Architecture:** デザイントークンは `variables.css` に集約し、`index.css` から `@import` 順序で読み込む。グローバル（`body`・`focus-visible`）は `base.css`、画面固有のレイアウト・パネル・表・タブは既存の `App.css` を段階的に変数参照へ置き換える（または `components/` 配下に分割）。React はクラス名を `.btn` / `.btn--*` など設計書の汎用クラスに寄せ、インラインの色指定（Recharts の `stroke` 等）は CSS 変数経由にする。

**Tech Stack:** React 19、Vite、CSS（変数ベース・ファイル分割）、Recharts、Vitest（happy-dom）、既存の `frontend/` 構成。

**参照:** @docs/design/design-ui-ux.md

---

### Task 1: デザイントークン `variables.css` の新規作成

**Files:**
- Create: `frontend/src/styles/variables.css`
- Modify: （次タスクで `index.css` から import）

**内容（設計書 1.1〜1.4 に合わせる）:**

- **スペーシング:** `--spacing-1`（4px）〜 `--spacing-12`（48px）を 8pt グリッドの列挙どおり定義。
- **カラー:** `--color-primary: #007AFF`、`--color-primary-dark`、`--color-primary-50`、`--color-primary-focus-ring`、セマンティック（成功・警告・エラー）、`--color-gray-50`〜`--color-gray-900`、`--color-text-primary` / `--color-text-secondary`、`--color-background` / `--color-background-elevated` / `--color-background-secondary`、`--color-border`。
- **タイポ:** `--font-size-large-title`（34px）〜 `--font-size-caption2`（11px）、`--font-weight-regular` / `--font-weight-semibold` / `--font-weight-bold`。
- **その他:** `--radius-panel: 14px`、`--radius-button: 10px`、`--radius-control: 6px`、シャドウ用の薄い値（パネル用）。

**Step 1: ファイル追加**

上記を `:root { ... }` にまとめた `variables.css` を追加する。

**Step 2: 768px 以下のタイポ一括縮小**

`variables.css` 末尾に `@media (max-width: 768px)` を入れ、設計書「768px 以下で一括縮小」に合わせて `--font-size-*` を 1 段階下げるか、`font-size` スケール用の補正係数を `--font-scale: 0.95` のように定義して base で掛ける（どちらか一貫した方針でよい）。

**Step 3: コミット**

```bash
git add frontend/src/styles/variables.css
git commit -m "feat(frontend): add Apple HIG design tokens (variables.css)"
```

---

### Task 2: グローバルベース `base.css` と `index.css` の配線

**Files:**
- Create: `frontend/src/styles/base.css`
- Modify: `frontend/src/index.css`

**Step 1: `base.css` を書く**

- `body`: `font-family` を設計書のスタック（`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, …`）に統一。`color: var(--color-text-primary)`、`background: var(--color-background)`、`line-height` は読みやすさ用に 1.45 前後を維持。
- **フォーカス:** グローバルで `outline: none` は使わず、ボタン・リンク・フォームはコンポーネント側で `:focus-visible` にリング。設計書 1.6 に従い、`*:focus-visible` のデフォルトを最小限にするか、個別クラスで上書きする方針を一文コメントで固定。
- `button { font: inherit; cursor: pointer; }` は現状 `index.css` から移行。

**Step 2: `index.css` を次の順で import**

```css
@import './styles/variables.css';
@import './styles/base.css';
```

既存の `index.css` の `body` / `button` ルールは `base.css` に移し、`index.css` は import のみに近づける。

**Step 3: 動作確認**

Run: `cd frontend && npm run build`（またはプロジェクト標準の `pnpm` / `npm` に合わせる）

Expected: ビルド成功。画面はまだ `App.css` が生色のため大きく変わらない可能性あり（次タスクで統一）。

**Step 4: コミット**

```bash
git add frontend/src/index.css frontend/src/styles/base.css
git commit -m "feat(frontend): wire global base styles and design tokens"
```

---

### Task 3: `App.css` をトークン参照に置換（色・余白・タイポ）

**Files:**
- Modify: `frontend/src/App.css`

**Step 1: ハードコードの削減**

- `#0d6efd`、`#ddd`、`#f4f6f9` 等を、対応する `var(--color-*)` / `var(--spacing-*)` に置換。
- `.app` の `padding` を `--spacing-*` に合わせる。
- `.header h1` を `--font-size-large-title`（設計書の h1）へ。

**Step 2: パネル・カード**

- `.stat` / `.empty-metrics`: 背景を `--color-background-elevated` または secondary、枠は `--color-border`、角丸 `--radius-panel` または設計書の stat 用に近い値。
- `.error-banner`: セマンティックのエラー色＋薄い背景（設計書のエラー領域のトーン）。

**Step 3: 表 `.table`**

- ヘッダー背景: gray-50 相当、`border-color: var(--color-border)`。

**Step 4: ビルド**

Run: `cd frontend && npm run build`

Expected: SUCCESS

**Step 5: コミット**

```bash
git add frontend/src/App.css
git commit -m "style(frontend): map App.css to design tokens"
```

---

### Task 4: ボタン・フォーム・タッチターゲット（HIG 44px）

**Files:**
- Modify: `frontend/src/App.css`
- Modify: `frontend/src/App.tsx`（クラス付与）

**Step 1: 汎用ボタンクラスを CSS で定義**

設計書 1.5 に基づき:

- `.btn` — 最小高さ 44px、`padding` は左右 `--spacing-4` 以上、角丸 `var(--radius-button)`。
- `.btn--filled` — 背景 `--color-primary`、文字白。
- `.btn--bordered` — 枠 `--color-primary`、背景透明。
- `.btn--gray` — 二次アクション（gray 系）。
- `:focus-visible` — 白＋青の二重リング（3px + 6px）を `box-shadow` で再現。
- `:disabled` — 不透明度と `cursor: not-allowed`。

**Step 2: フォーム**

- `input:not([type="checkbox"])`、`select`、`textarea` — 高さ 44px（textarea は `min-height: 88px`）、角丸 `--radius-control`、枠 `--color-border`、プレースホルダー色 gray-400。
- `:focus-visible` — 青枠＋ 2px リング（設計書どおり）。

**Step 3: `App.tsx` でボタンにクラス付与**

- 認証行の「保存」、各パネルの「再読込」「追加」「接続テスト」「切替」「削除」「再取得」「手動で収集」など、主アクションは `.btn.btn--filled`、破壊的操作や二次は `.btn.btn--gray` など方針を決めて一貫適用。

**Step 4: 手動確認**

ブラウザでタブ・フォーム・ボタンの高さとフォーカスリングを確認。

**Step 5: コミット**

```bash
git add frontend/src/App.css frontend/src/App.tsx
git commit -m "feat(frontend): HIG button and form styles with 44px targets"
```

---

### Task 5: タブナビ（`.tabs`）の HIG トーン

**Files:**
- Modify: `frontend/src/App.css`

**Step 1: アクティブ状態**

- アクティブタブの下線色を `--color-primary`（#007AFF）に変更済みであることを確認。
- 非アクティブは `--color-text-secondary`、ホバーで背景 `--color-background-secondary` など。

**Step 2: タッチターゲット**

- タブボタンも高さ最低 44px、`padding` を `--spacing-*` で確保。

**Step 3: コミット**

```bash
git add frontend/src/App.css
git commit -m "style(frontend): refine tabs for HIG alignment"
```

---

### Task 6: Recharts と空状態の色の統一

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.css`（必要ならチャート用ラッパー）

**Step 1: 線グラフの色**

`<Line stroke="#0d6efd" />` を `stroke="var(--color-primary)"` に変更（ブラウザでは SVG が CSS 変数を解決できる）。

**Step 2: `CartesianGrid` / 軸**

可能なら `stroke` を gray-200 相当の変数に寄せる（Recharts の props で色指定）。

**Step 3: コミット**

```bash
git add frontend/src/App.tsx frontend/src/App.css
git commit -m "style(frontend): align chart colors with design tokens"
```

---

### Task 7: アクセシビリティの最小補強（設計書 1.6）

**Files:**
- Modify: `frontend/src/App.tsx`

**Step 1: エラーバナー**

`{err && <div className="error-banner" role="alert">...</div>}` のように `role="alert"` を付与。

**Step 2: 将来のフォーム検証に備えたメモ**

現状クライアント側バリデーションが薄い場合はコード変更は最小。設計書どおり `aria-invalid` はフィールドにエラー時のみ付与するため、本タスクでは「エラーバナーのみ」でよい。

**Step 3: コミット**

```bash
git add frontend/src/App.tsx
git commit -m "a11y(frontend): add role=alert to error banner"
```

---

### Task 8: 検証（ビルド + 既存テスト）

**Files:**
- （変更なし、コマンドのみ）

**Step 1: フロントエンドテスト**

Run: `cd frontend && npm run test`（`package.json` の `vitest run`）

Expected: 既存の `src/datetime/*.test.ts` がすべて PASS。

**Step 2: ビルド**

Run: `cd frontend && npm run build`

Expected: SUCCESS。

**Step 3: （任意）リンター**

プロジェクトに ESLint がある場合は `npm run lint` を実行。

**Step 4: コミット**

テストのみ通過確認でコード差分がなければコミット不要。

---

## 完了条件チェックリスト

- [ ] `variables.css` にスペーシング・色・タイポ・半径が設計書と整合
- [ ] 主要ボタン・入力・セレクト・タブが 44px 前後のタッチターゲット
- [ ] `:focus-visible` でリングが視認できる（設計書の二重リング方針）
- [ ] プライマリカラーが Apple Blue（#007AFF）系に統一
- [ ] Recharts のアクセント色がトークンと一致
- [ ] `frontend` のビルドと既存 Vitest が通過

---

## 注意（YAGNI）

- 新しい UI ライブラリ（MUI/Chakra 等）は導入しない。
- ダークモードは設計書に明示がなければスコープ外（ライトのみでよい）。
- タスクカードや `details` ドロップダウンは現 UI に存在しないため、必要になった段階で設計書 1.5 のコンポーネントを追加する。
