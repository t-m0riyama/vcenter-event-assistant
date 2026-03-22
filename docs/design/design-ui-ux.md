# UI/UX・技術選定

UI/UX方針をまとめたドキュメント。

---

## 1. デザイン（UI/UX方針・見た目）

### 1.1 方針

- **システムUI寄せ** — フォントは `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, …` のシステムフォントスタック。Apple Human Interface Guidelines（HIG）を参考にしたトーンで統一。
- **8pt グリッド** — 余白・パディングは 4px / 8px / 12px / 16px / 24px / 32px / 48px の変数（`--spacing-*`）で統一。
- **タッチターゲット** — ボタン・入力欄は最小高さ 44px を確保し、操作しやすさを優先。
- **CSS 構成** — 役割ごとにファイル分割。`variables.css` でテーマを定義し、他ファイルは原則として変数のみ参照。
- **命名規則** — レイアウト・パネル・ボタンは汎用クラス（`.panel`, `.btn`）を使用。ヘルプパネルなどUIブロックは BEM（`.help-panel__title`）を使用。


### 1.3 カラーパレット

- **プライマリ** — `--color-primary: #007AFF`（Apple Blue）、濃い青 `--color-primary-dark`、薄い背景 `--color-primary-50`、フォーカスリング `--color-primary-focus-ring`。
- **セマンティック** — 成功 `#34C759`、警告 `#FFCC00`、エラー `#FF3B30`。
- **グレースケール** — `--color-gray-50` ～ `--color-gray-900`。テキストは `--color-text-primary`（gray-900）/ `--color-text-secondary`（gray-500）。
- **背景・枠** — `--color-background`（白）、`--color-background-elevated`、`--color-background-secondary`、`--color-border`（gray-200）。

### 1.4 タイポグラフィ

- **サイズ** — Dynamic Type 風の変数（`--font-size-large-title` 34px ～ `--font-size-caption2` 11px）。768px 以下で一括縮小。
- **ウェイト** — regular 400、semibold 600、bold 700。
- **用途** — 見出し（h1: large-title、h2: title3）、本文・ボタン（body）、ラベル・注釈（subhead / footnote）。

### 1.5 コンポーネント

- **パネル** — 白背景・1px 枠・角丸 14px・軽いシャドウ。ヘッダーは flex でタイトルとアクションを両端配置。
- **ボタン** — 角丸 10px。filled（青塗り）、bordered（青枠）、tinted（青塗り・メニュー用）、gray（二次アクション）。フォーカス時は白＋青の二重リング（3px + 6px）。
- **フォーム** — 入力・セレクト・テキストエリアは高さ 44px（textarea は最小 88px）、角丸 6px、枠線。フォーカス時は青枠＋青の 2px リング。プレースホルダーは gray-400。
- **エラー状態** — `.invalid` で赤枠＋赤の 3px シャドウ。フォーカス時は赤を維持しつつ外側に青の 6px リングでフォーカス視認性を確保。
- **ドロップダウン** — `<details>` ベース。メニューは絶対配置・影付き・角丸。項目はホバーで gray-100、フォーカスで primary-50 背景＋青 2px リング。
- **タスクカード** — 背景 elevated、枠・角丸 10px。ヘッダーにドラッグハンドル（フォーカスはボタン同様の二重リング）と削除ボタン。グリッドは 640px / 768px で 2/3 カラムに変化。

### 1.6 アクセシビリティ（視覚）

- フォーカスは `:focus-visible` でリングを表示（outline は削除）。
- エラー時は `aria-invalid` と `.invalid` を併用。エラーメッセージ領域は赤枠・薄い赤背景で明示。
- ドラッグハンドルは `role="button"` と `aria-label="タスクを並べ替える"` を付与。

---

## 2. UI/UX 方針（画面構成・振る舞い）

- **単一ページ** — 同一画面に配置。
- **アクセシビリティ** — バリデーション時に `aria-invalid` と `.invalid` クラスでフィールドの不正を表現。

