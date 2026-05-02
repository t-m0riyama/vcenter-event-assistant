# 巨大ファイルの分割 — 実装プラン

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.
> ご要望通り、バックエンドのテスト・Lintには `uv` を使用します。

**Goal:** 肥大化した `App.css`, `App.tsx`, `settings.py` を論理的な単位に分割し、コードベースの見通しを改善する。

## Task 1: `App.css` の機能単位への分割
- **Target:** `frontend/src/App.css`
- **Actions:**
  1. `frontend/src/panels/` 以下の主要パネル（Events, Metrics, Digests, Alerts, Chat, Settings 等）ごとに `.css` ファイルを新規作成する。
  2. `App.css` から該当するクラス定義を各パネルの CSS ファイルに移動する。
  3. 各パネルのルートコンポーネント（例: `EventsPanel.tsx`）の先頭で `import './EventsPanel.css'` のようにインポートを追加する。
  4. グローバルな定義（`:root`, `.app`, `.header`, `.tabs`, `.panel` など）は `App.css` に残す。
- **Verification:**
  - `npm run build` で CSS が正しくビルドできるか確認。
- **Commit:** `refactor: split App.css into panel-specific css files`

## Task 2: `App.tsx` の Provider 層の抽出
- **Target:** `frontend/src/App.tsx`, `frontend/src/components/AppProviders.tsx` (新規)
- **Actions:**
  1. `frontend/src/components/AppProviders.tsx` を作成し、`ThemeProvider` から `ChatSamplePromptsProvider` までの6階層の Provider をまとめるコンポーネントを定義する。
  2. `App.tsx` のインポートと JSX ツリーを整理し、ネスト部分を `<AppProviders>` に置き換える。
- **Verification:**
  - `npm run build` でコンパイルが通ること。
  - ESLint などの静的解析エラーが出ないこと。
- **Commit:** `refactor: extract AppProviders from App.tsx`

## Task 3: `settings.py` の Mixin 分割
- **Target:** `src/vcenter_event_assistant/settings.py`
- **Actions:**
  1. Pydantic `BaseModel` を継承した以下の Mixin クラスを作成し、`Settings` クラス内のプロパティ・バリデータを移動する。
     - `DatabaseSettingsMixin`: データベース関連 (`database_url`, リテンション期間など)
     - `LlmSettingsMixin`: LLM 接続や LangSmith 関連
     - `AlertSettingsMixin`: SMTP およびアラート関連
     - `AppLogSettingsMixin`: ロギングやスケジューラ等の実行設定関連
  2. メインの `Settings(BaseSettings, DatabaseSettingsMixin, LlmSettingsMixin, ...)` のように多重継承を用いて再構成する。
  3. 各機能のバリデータ（`@field_validator`）も対応する Mixin クラス内に移動する。
- **Verification:**
  - `uv run ruff check src/vcenter_event_assistant/settings.py` で Lint エラーがないことを確認。
  - `uv run pytest tests/` で設定の読み込みやテストが壊れていないことを確認。
- **Commit:** `refactor: split settings.py monolithic class using mixin pattern`
