# WEB 検索が行われる条件

本書は、vCenter Event Assistant が外部の WEB 検索 API（Tavily / Firecrawl）を呼び出す
条件を整理したものです。閉域網での運用設計や、意図しない外部送出がないことの確認に
使ってください。

対象コード: `services/research/search_provider.py`（プロバイダ組み立て）、
`services/research/research_job.py`（事前調査ジョブ）、
`services/chat/chat_web_search.py`（チャットの WEB 検索）。

## 全体像

WEB 検索が実際に実行される経路は次の 2 つだけです。

| 経路 | 起点 | 検索クエリの生成 |
|---|---|---|
| A. 事前調査ジョブ | スケジューラ（`research_interval_seconds` 間隔） | 固定テンプレート（可変部は event_type のみ） |
| B. チャットの WEB 検索 | ユーザーが「WEB 検索を許可」を ON にしたチャット送信 | LLM が発行（送出前にサニタイズ） |

ダイジェストやチャットへの「調査結果の付記」（`research_attach.py`、
`research_attach_max_items` 件まで）は **DB にキャッシュ済みの調査結果を読むだけ** で、
検索は実行しません。

## 共通の前提条件（両経路）

検索プロバイダは `build_search_provider()` が組み立てます。次の **すべて** を満たさない
限り `None` が返り、WEB 検索機能全体が **静かに無効化** されます（例外・エラーには
なりません。閉域網では未設定のままでよい設計です）。

1. `WEB_RESEARCH_ENABLED=true`（既定 true。マスタースイッチ）
2. `SEARCH_PROVIDER` で選択したプロバイダの接続情報が設定済み
   - `tavily`（既定）: `TAVILY_API_KEY` が必須
   - `firecrawl`: `FIRECRAWL_BASE_URL`（セルフホスト）**または** `FIRECRAWL_API_KEY`
     （クラウド）のいずれか

補足:

- 接続情報は空文字・空白のみでも「未設定」扱いです（None に正規化）。
- 選択していないプロバイダの設定は無視されます（例: `SEARCH_PROVIDER=tavily` のとき
  `FIRECRAWL_API_KEY` があっても firecrawl は使われない）。
- セルフホスト Firecrawl の `/search` は、裏に検索バックエンド（SearXNG または
  Serper 等）の構成が必要です（インフラ側の前提）。
- 設定は環境変数 / `.env` 由来のため、変更の反映にはアプリの再起動が必要です。

## 経路 A: 事前調査ジョブ（自動）

高スコアの event_type について原因・対処情報を事前に検索し、結果を
`event_type_research` テーブルにキャッシュするジョブです。

### 実行される条件

すべて満たしたときのみ検索が実行されます。

1. **ジョブが登録されている**: `SCHEDULER_ENABLED=true` かつ、アプリ起動時点で
   検索プロバイダが構成済み（未構成なら `web_research` ジョブ自体が登録されない。
   `jobs/scheduler.py`）
2. **サイクル開始時にもプロバイダ構成を再確認**（未構成なら即 no-op）
3. **調査対象の event_type が存在する**。対象は次の条件をすべて満たすもの:
   - 直近 `RESEARCH_EVENT_LOOKBACK_HOURS`（既定 24 時間）以内に発生したイベントで、
     `notable_score >= RESEARCH_EVENT_SCORE_THRESHOLD`（既定 40）のものがある
   - その event_type の調査キャッシュが **存在しない、または鮮度切れ**（下記 TTL）

### キャッシュの鮮度（TTL）— 再検索が起きるタイミング

キャッシュが fresh な間は同じ event_type を再検索しません。

| キャッシュの状態 | 鮮度期限 | 既定値 |
|---|---|---|
| `ok`（調査成功） | `RESEARCH_SUCCESS_TTL_DAYS` | 90 日 |
| `no_result`（成果なし） | `RESEARCH_NO_RESULT_TTL_DAYS` | 30 日 |
| `error`（検索失敗） | `RESEARCH_ERROR_RETRY_MINUTES` | 60 分 |

`error` の短い TTL は、API キー不備等で毎サイクル外部 API を叩き続けることを
防ぐための再試行間隔です。

### 実行量の上限

- 実行間隔: `RESEARCH_INTERVAL_SECONDS`（既定 600 秒）
- 1 サイクルの検索実行上限: `RESEARCH_MAX_PER_CYCLE`（既定 5 件、スコア降順に選択）
- 1 検索あたりの取得件数: `SEARCH_MAX_RESULTS`（既定 5 件）

### 外部に送出される内容

検索クエリは固定テンプレート
`VMware vSphere event "{event_type}" cause resolution` で生成され、可変部は
event_type のみです。ホスト名・IP 等の環境固有情報が混入しないことを構造的に
保証しています（`research_service.build_research_query`）。

## 経路 B: チャットの WEB 検索（ユーザー起点）

チャット応答の生成中に、LLM が `web_search` ツール（function calling）で検索を
実行する経路です。

### 実行される条件

すべて満たしたときのみ検索が実行され得ます。

1. **共通の前提条件**（プロバイダ構成済み）を満たす。UI はこの可否を
   `GET /api/config` の `chat_web_search_available` で取得し、未構成なら
   チェックボックス自体を出しません
2. **ユーザーがそのメッセージで「WEB 検索を許可」を ON にしている**
   （`ChatRequest.enable_web_search`。リクエスト単位のオプトイン）
3. **LLM が検索を必要と判断してツールを呼び出す**（許可しても、質問内容によっては
   LLM が検索せずに回答することがある）

### 実行量の上限

- 1 メッセージあたりの検索回数: `CHAT_WEB_SEARCH_MAX_CALLS`（既定 2 回）。
  上限到達後のツール呼び出しには「既知の情報で回答」を返し、検索は実行しない
- 1 検索あたりの取得件数: `SEARCH_MAX_RESULTS`（既定 5 件）

### 外部に送出される内容

- LLM が発行した検索クエリは、外部送出前に IPv4 アドレス除去のサニタイズを通します
  （`sanitize_search_query`）。会話・コンテキスト自体は既存の LLM 入力匿名化で
  トークン化済みのため、生のホスト名等は原則含まれません
  （詳細: [llm-input-anonymization.md](llm-input-anonymization.md)）
- ツール定義でも、固有名・IP・匿名化トークンをクエリに含めないよう LLM に指示
  しています

### 失敗時の挙動

検索の失敗はツール応答として LLM に伝え、応答生成自体は継続します（チャットが
エラーで落ちることはありません）。

## WEB 検索が行われない条件（まとめ）

次のいずれかに当てはまる場合、外部の検索 API は一切呼ばれません。

- `WEB_RESEARCH_ENABLED=false`
- 選択プロバイダの接続情報が未設定（tavily: API キーなし / firecrawl: base_url も
  キーもなし）
- 経路 A: `SCHEDULER_ENABLED=false`、調査対象の event_type がない、または全対象の
  キャッシュが TTL 内
- 経路 B: 「WEB 検索を許可」を ON にしていない、または LLM がツールを呼ばなかった
- 経路 B: 検索回数が `CHAT_WEB_SEARCH_MAX_CALLS` の上限に達した後

## 関連設定一覧

| 環境変数 | 既定値 | 役割 |
|---|---|---|
| `WEB_RESEARCH_ENABLED` | `true` | WEB 調査機能のマスタースイッチ |
| `SEARCH_PROVIDER` | `tavily` | 検索プロバイダ（`tavily` \| `firecrawl`） |
| `TAVILY_API_KEY` | なし | Tavily API キー（tavily 選択時に必須） |
| `FIRECRAWL_API_KEY` | なし | Firecrawl API キー（クラウド利用時に必須） |
| `FIRECRAWL_BASE_URL` | なし | セルフホスト Firecrawl のベース URL |
| `SEARCH_TIMEOUT_SECONDS` | `15` | 検索 API 呼び出しのタイムアウト |
| `SEARCH_HTTP_PROXY` | なし | 検索 API 用 HTTP プロキシ（vCenter 用とは別） |
| `SEARCH_MAX_RESULTS` | `5` | 1 クエリあたりの取得件数 |
| `RESEARCH_INTERVAL_SECONDS` | `600` | 事前調査ジョブの実行間隔 |
| `RESEARCH_MAX_PER_CYCLE` | `5` | 1 サイクルの検索実行上限 |
| `RESEARCH_EVENT_SCORE_THRESHOLD` | `40` | 調査対象とする notable_score の下限 |
| `RESEARCH_EVENT_LOOKBACK_HOURS` | `24` | 調査対象イベントの遡り時間 |
| `RESEARCH_SUCCESS_TTL_DAYS` | `90` | 調査成功キャッシュの鮮度期限 |
| `RESEARCH_NO_RESULT_TTL_DAYS` | `30` | 成果なしキャッシュの鮮度期限 |
| `RESEARCH_ERROR_RETRY_MINUTES` | `60` | 検索失敗後の再試行間隔 |
| `CHAT_WEB_SEARCH_MAX_CALLS` | `2` | チャット 1 メッセージあたりの検索上限 |
