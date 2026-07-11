# copilot_cli の WEB 検索対応（2026-07-11 grilling）

チャット（モード B）とダイジェスト（モード A の調査要約）を、LLM プロバイダが
`copilot_cli` の場合でも WEB 検索対応にする。`/grill-me` セッションで確定した設計判断のまとめ。

**前提ドキュメント:** [2026-07-08-web-research-attach-design.md](2026-07-08-web-research-attach-design.md)
本ドキュメントは同設計の **#8（copilot_cli で要約無効化）** と
**モード B の含意（copilot_cli でモード B 無効化）** を撤回・改訂する。

## 背景（現状の除外理由）

| 箇所 | 現状 | 除外の技術的理由 |
|------|------|-----------------|
| チャット モード B | `chat_web_search_available()` が `copilot_cli` で False | `chat_web_search.py` が LangChain `bind_tools` の function calling ループ前提。copilot 分岐は単発プロンプト（`available_tools=[]`・全ツール権限拒否） |
| 調査要約（モード A） | `_summarize_results()` が `copilot_cli` で要約スキップ（設計判断 #8） | LangChain ChatModel 非対応という理由のみ。**要約は単発プロンプトで足り、function calling は不要** |

## 確定した設計判断

| # | 論点 | 決定 | 理由・補足 |
|---|------|------|-----------|
| C-1 | 対象範囲 | **チャット モード B + 調査要約の両方を解禁** | ダイジェスト側は既存実装と同様に event_type 起点の調査ジョブの枠内。ジョブ構造は変えず要約だけ copilot 対応 |
| C-2 | チャットの検索機構 | **github-copilot-sdk のカスタムクライアントツール** | SDK は `create_session(tools=[Tool])` を正式サポート（Pydantic スキーマ自動生成・`skip_permission`）。検索実行はサーバ側ハンドラ内なので、既存のサニタイズ・出典収集・回数上限をそのまま適用できる。テキストプロトコル自前実装は不採用 |
| C-3 | 調査要約の機構 | **単発プロンプト（`run_copilot_cli_digest_completion` 相当）** | function calling 不要。既存の `_SUMMARY_SYSTEM_PROMPT` + 検索結果テキストをそのまま流用 |
| C-4 | Copilot 組み込みツール | **全拒否を維持** | 外部送出は自前の `web_search`（Tavily 経由・IPv4 サニタイズ済み）のみに限定。`available_tools=[]` + `deny_permission` は変えず、カスタムツールは `skip_permission=True` で登録 |
| C-5 | タイムアウト | **検索有効時は自動延長。新設定は増やさない** | `timeout_seconds` を検索回数上限に応じて割り増し（例: + `chat_web_search_max_calls` × 30 秒）。使い方・API 面は openai/gemini 実装と同一に保つ（`enable_web_search` フラグ・出典ブロック・免責表示すべて共通） |
| C-6 | 要約のプロセスコスト | **許容（直列実行のまま）** | 調査ジョブは低頻度（新規 event_type のみ・サイクル上限 N 件）。要約 1 件ごとの CLI サブプロセス起動は実用上問題なし。並列度制限は導入しない |
| C-7 | ツール登録不能時 | **検索なしで続行（graceful degrade）** | 古い CLI 等でカスタムツール登録が失敗しても応答生成は継続（既存の「検索失敗は LLM に伝えて続行」と同じ失敗分離ポリシー） |
| C-8 | リリース | **一括解禁（1 フェーズ）** | チャット・要約とも同時に copilot_cli 除外を撤去。検索プロバイダ未構成なら従来どおり全機能 OFF なのでリスク限定的 |

## 設計上の含意

- **既存の安全機構はすべて共通化して適用する**（openai/gemini 経路との等価性が受け入れ条件）:
  - クエリの `sanitize_search_query`（IPv4 除去）
  - 検索回数上限 `chat_web_search_max_calls`（ハンドラ側でカウントし、超過時は「上限到達・既知情報で回答」を返す）
  - 出典ブロックはツールハンドラが収集した実在 URL からサーバ側で機械的に生成（`render_web_search_sources` 流用）
  - 検索結果への「結果中の指示に従わない」前置き（`_format_results_for_llm` 流用）
- `chat_web_search_available()` の `provider != "copilot_cli"` 条件を撤去 → config API の
  「web 検索利用可」フラグが自動的に true になり、UI トグルもそのまま出る（追加 UI 変更なし）。
- `_summarize_results()` の copilot 分岐を「スキップ」から「copilot 用単発要約」に置換。
  失敗時は従来どおり `(None, None, error)` で要約なし保存（R-2 失敗分離を維持）。
- ツールハンドラは async。SDK の `send_and_wait` がツール呼び出しを内包して完結するため、
  チャット側の呼び出し面（`run_copilot_cli_chat_completion` のシグネチャ拡張）は
  「出典リストも返す」形に変わるのが主な差分。

## 未確定・実装時に決める項目

| 項目 | 推奨 |
|------|------|
| タイムアウト割り増しの係数 | 検索 1 回あたり +30 秒程度。定数でよい（Settings 化しない、C-5） |
| ツール登録失敗の検出方法 | `create_session(tools=...)` の例外/エラー応答を捕捉してツールなしで再セッション or そのまま続行。SDK の実挙動を実装時に確認 |
| copilot 用検索ループの共通化度合い | `chat_web_search.py` の整形・出典関数は流用し、ループ本体（LangChain 用 / SDK ハンドラ用）は別実装で可。無理に抽象化しない |
| テスト方法 | `CopilotClient` をモックし、ツールハンドラ単体（サニタイズ・上限・失敗継続）と統合（出典ブロック生成）を検証 |
