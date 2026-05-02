# 巨大ファイルの分割 — 設計ドキュメント

**日付:** 2026-05-02
**目的:** 開発の過程で肥大化した主要ファイル（`App.css`, `App.tsx`, `settings.py`）を責務ごとに分割し、可読性と保守性を向上させる。

## 背景

機能追加を繰り返した結果、以下の3つのファイルが巨大化し、コードの理解や修正時のコンフリクトリスクが高まっている。

1. **`frontend/src/App.css` (約1360行)**:
   アプリケーション全体のスタイル、各パネル（Events, Chat, Settings 等）のスタイル、UI コンポーネントのスタイルが単一ファイルに集中している。
2. **`frontend/src/App.tsx` (約260行)**:
   ルーティングや状態管理に加え、複数の Context Provider（`ThemeProvider`, `TimeZoneProvider` など全6種）のネストが非常に深く、コードのインデントと見通しを悪化させている。
3. **`src/vcenter_event_assistant/settings.py` (約370行)**:
   データベース、LLM 接続、アラート、保持期間など、あらゆる環境変数の定義とバリデーションロジック（`@field_validator`）が1つの `Settings` クラスに詰め込まれている。

## 設計方針

### 1. `App.css` の機能単位への分割
- **アプローチ**: グローバルなスタイル（レイアウト、変数）のみを `App.css` に残し、特定のパネルやコンポーネントに依存するスタイルはそれぞれのディレクトリに `.css` ファイルとして切り出す。
- **配置**: 例として `frontend/src/panels/chat/ChatPanel.css` などを作成し、対象の `.tsx` で直接インポートする。

### 2. `App.tsx` の Provider 層の抽出
- **アプローチ**: コンテキストを提供する Provider の多重ネストを専用のコンポーネントに切り出す。
- **実装**: `frontend/src/components/AppProviders.tsx` を新規作成し、`children` を受け取るコンポーネントとして全ての Provider を集約する。これにより `App.tsx` の責務を純粋な「レイアウトとタブ切り替え」に絞る。

### 3. `settings.py` の Mixin 分割
- **アプローチ**: `settings.py` が1ファイルで完結する利便性を維持しつつ、クラスの巨大化を防ぐため、Pydantic の `BaseModel`（またはプレーンなクラス）を用いた **Mixin パターン** を採用する。
- **実装**: 関連する設定項目とバリデータごとに、同じファイル内で（または別モジュールとして） `DatabaseSettingsMixin`, `LlmSettingsMixin`, `AlertSettingsMixin` などのクラスに分離し、最終的な `Settings` クラスはこれらを多重継承して構成する。これにより、各ドメインの設定がブロックとして独立する。

## 品質保証（QA）
- バックエンドの修正確認には、リクエスト通り **`uv` コマンド** (`uv run ruff check`, `uv run pytest`) を徹底して使用する。
- API や UI の外部的な振る舞いは一切変更しない（純粋なリファクタリング）。
