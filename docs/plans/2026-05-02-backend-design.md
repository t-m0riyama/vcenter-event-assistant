# バックエンド設計改善 — 設計ドキュメント

**日付:** 2026-05-02
**目的:** FastAPI アプリケーションの肥大化を防ぎ、コードの凝集度を高めるため、バックエンドの設計上の課題3点をリファクタリングする。

## 背景と課題

1. **`main.py` 内のインライン `run_ingest_now` エンドポイント**
   - **課題**: `create_app()` の内部で `api.post("/ingest/run")` というルートがインライン定義され、DBセッション管理やインジェスト処理のロジックが直接記述されている。これにより `main.py` が肥大化し、ルーティングの責務が混在している。
2. **サービス間の `settings` 引き回し**
   - **課題**: 多くのサービス関数（例: `chat_llm.py` 内の関数など）が `settings: Settings` を引数として受け取っている。`settings.py` の `get_settings()` は `@lru_cache` でメモ化されており、どこから呼んでもコストは無いため、呼び出し元（APIのController層など）からバケツリレーのように引き回すのはボイラープレートの増加を招いている。
3. **`chat_llm.py` の `run_period_chat` と `build_chat_preview` のロジック重複**
   - **課題**: ペイロードの準備、トークン予算へのフィッティング、メタデータ（`ChatLlmContextMeta`）の構築という約15行のロジックが、上記2つの関数で完全に重複している。

## 設計方針

### 1. `ingest` ルーターの分離
- `src/vcenter_event_assistant/api/routes/ingest.py` を新規作成する。
- `main.py` のインライン関数 `run_ingest_now` をこのルーターモジュールに移動する。
- `main.py` では `from .api.routes.ingest import router as ingest_router` とし、`api.include_router(ingest_router)` として登録する。

### 2. `settings` 引き回しの廃止（Dependency Injectionの見直し）
- `chat_llm.py` などのサービス関数（`run_period_chat`, `build_chat_preview` など）の引数から `settings: Settings` を削除する。
- 代わりに、各関数内で `settings = get_settings()` を直接呼び出す。
- これに伴い、呼び出し元（例: `api/routes/chat.py` などのルーター）から `settings` を渡している部分を削除し、不要な `Depends(get_settings)` をクリーンアップする。

### 3. LLM コンテキスト構築ロジックの共通化
- `chat_llm.py` 内に、重複しているコンテキスト構築ロジックをまとめたプライベート関数 `_build_chat_context_and_meta` を作成する。
- 戻り値として `(block, trimmed_msgs, meta, reverse_map)` を返すようにし、`build_chat_preview` と `run_period_chat` の両方がこれを呼び出す形にリファクタリングする。
