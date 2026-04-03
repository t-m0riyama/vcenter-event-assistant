# LangSmith トレーシング設計

## 目的

期間チャットとバッチダイジェストの LLM 呼び出しを LangSmith で観測し、`period_chat` と `digest` をメタデータ・タグで区別できるようにする。

## 既定と有効化

- 環境変数 **`LANGSMITH_TRACING_ENABLED`** は既定 **`false`**。明示的に `true` にしたときだけ LangSmith 向けコールバックを付与する。
- **`LANGSMITH_API_KEY`** が空のときは、トレース送信に使うクライアントを組み立てない（タグ・metadata のみ付与し、callbacks は付けない）。

## プライバシー・運用

- トレースをオンにすると、LangChain の実行経路に応じて **プロンプト全文やモデル入出力が LangSmith 側に記録される可能性**がある。入力には vCenter 由来のホスト名・イベント本文などが含まれうる。
- **本番環境で有効化するかは運用判断**とする。社内規程やデータ分類に応じ、検証環境のみ・専用プロジェクト・リージョン・保持期間などを LangSmith 側設定で合わせること。
- **LangSmith Datasets / Evals**（回帰評価パイプライン）は本設計のスコープ外とし、匿名化フィクスチャの整備が整い次第、別タスクで後追いする。

## RunnableConfig の契約

### tags

- 常に **`vea`** を含める。
- **`run_kind`** と同じ文字列をタグに含める: `period_chat` または `digest`。

### metadata（キー一覧）

| キー | 必須 | 値 |
|------|------|-----|
| `run_kind` | はい | `period_chat` または `digest` |
| `llm_provider` | はい | 実効プロファイルのプロバイダ（`run_kind == digest` なら `LLM_DIGEST_*` のみ、`period_chat` なら `LLM_CHAT_*` をマージした値。`resolve_llm_profile`） |
| `llm_model` | はい | 同上の実効モデル ID |
| `vcenter_id` | いいえ | チャット API で指定された場合のみ（文字列） |
| `digest_kind` | いいえ | `run_kind == digest` のときのみ（日次・週次・月次などの kind 文字列） |

## 実装参照

- 設定: `Settings` の `langsmith_*` フィールド
- 組み立て: `vcenter_event_assistant.services.llm_tracing.build_llm_runnable_config`
