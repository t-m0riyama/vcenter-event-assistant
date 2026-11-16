# タイムラインを初動調査に使える機能へ作り直す

## Context

タイムラインは障害の初動調査を早くするための機能だが、現状は効果が出ていない。コードを読んで分かった原因は次のとおり。

- 中身が集計値の文字列だけ（「イベント件数: 42」「◯◯Event (3件, max score=80)」）。対象のホスト・VM もメッセージも出ず、クリックもできない。
- 「含めるメトリクス」を選ばないと時間バケットの集計が走らず、ダイジェスト用の上位イベント群を最終発生時刻に置くだけになる（`chat_context_payloads.py` の `want_metrics` 分岐）。
- 赤い「alert」はスコア上位のイベント種別で、通知履歴（`alert_history` / `alert_states`）もログ（`log_records`）も入っていない。
- 自動トリガーの閾値が直書き（`chat_context_timeline_entries.py`）。メトリクスはバケットごとの点で並び、超過の開始・終了が読めない。
- 通知履歴・イベント・概要からの入口がなく、毎回フォームに入力して生成ボタンを押す。URL 共有もできない。
- 表示が UTC 固定。重要度フィルタは種別の言い換えで機能していない。
- スナップショットは条件だけを保存し、開くと再集計する。保持期間（7 日）を過ぎると中身が消える。

根本原因は、チャットの LLM 用コンテキスト（件数の集計）を画面にそのまま流用していること。

**決定事項（利用者に確認済み）**

- 起点は 4 つすべてに対応する: アラート通知の時刻、特定のホスト・VM、気になるイベント、直近の全体状況。
- タイムライン専用の API と画面を作り直す。チャット側の集計（`build_chat_incident_timeline*`、チャットのプレビュー内の `IncidentTimelinePanel`）は変えない。
- スナップショットは結果も保存するよう直す。

**目指す姿**: 時刻か対象を 1 つ決めれば、その前後で「何が・どこで・どの順に」起きたかが個々のレコードまで見え、そこからイベント・ログ・グラフへ 1 クリックで移れる。

## 設計

### 1. 専用 API: `POST /api/incident-timeline/view`（viewer 以上）

`src/vcenter_event_assistant/api/routes/incident_timeline.py` に追加する。既存の `POST /api/incident-timeline` は旧スナップショットとの互換のため残す。

リクエスト（`api/schemas/` に新規 `incident_timeline_view.py`）:

- `from` / `to`（必須）、`vcenter_id`、`entity`（ホスト・VM 名の部分一致）、`anchor_time`（起点、任意）
- `min_score`（既定 1）、`sources`（`event` / `alert` / `metric` / `log`、既定は全部）
- メトリクス閾値 4 種（既定は `periodMetricThresholdDefaults.ts` と同じ 80 / 85 / 75 / 75）
- `item_limit`（既定 500、上限 1000）

レスポンス:

- `overview`: 等幅バケットごとの件数（`event_total` / `event_notable` / `alert` / `metric_breach` / `log_error`）。件数 0 のバケットも埋めて返す。
- `items`: 個々の出来事（時刻順、`truncated` で打ち切りを示す）。共通の項目は `kind`、`timestamp_utc`、`end_utc`（区間のとき）、`level`、`title`、`detail`、`entity_name`、`entity_type`、`vcenter_id`、`score`、`count`（連続する同種をまとめた件数）、`ref`（元レコードへの参照）。
  - **event**: `notable_score >= min_score` の個別イベント。同じ `(event_type, entity_name)` が連続するときは 1 件にまとめ、`count` と最初・最後の時刻を持たせる。`ref.event_id`。
  - **alert**: 期間内の `AlertHistory`（発火・解消、ルール名、レベル）。`context_key` は `alert_eval_common.py` の形式（イベント種別、または `vcenter_id:moid`）から対象を解決する。
  - **metric**: 閾値超過を「開始〜終了・ピーク値」の区間にまとめる。集計は `chat_period_metrics.py` の `build_chat_period_metrics` と `compute_chat_bucket_seconds` を再利用する。
  - **log**: 重大度が error 以上の `LogRecord`。同じ `(host, log_kind)` の連続はまとめる。
- `highlights`:
  - `first_signal`: 期間内で最初の重要な出来事
  - `top_entities`: 出来事の多い対象の上位 5 件（件数と最初の時刻）
  - `new_event_types`: 直前の同じ長さの期間には無く、今回初めて出たイベント種別

サービスは新規 `services/incident_timeline_view.py` に置く（種別ごとの収集関数と、まとめ・ハイライトの純粋関数に分ける）。重い集計なので既存の仕組みを再利用する。

- 同時実行数の上限: `services/chat/aggregation_limiter.py` の `aggregation_slot`（503 と `Retry-After`）
- 行数の上限: `context_aggregation_max_rows`（超過は 422）
- 時刻バケット: `services/sql_time.py` の `bucket_index_expr` / `truncate_to_second`

### 2. 画面の作り直し（`frontend/src/panels/timeline/`）

上から順に次の構成にする。

1. **条件バー**: 期間プリセット（直近 1 時間 / 6 時間 / 24 時間、起点があるときは ±15 分 / ±1 時間 / ±6 時間）、vCenter、対象の検索、種別の切り替え。閾値は「詳細設定」に畳む。開いたときと条件変更時に自動で読み込み、「生成」ボタンは「更新」に置き換える。既定は直近 1 時間。
2. **件数の俯瞰**: 種別ごとの積み上げ棒グラフ（recharts、グラフタブと同じ）。起点に縦線を引く。棒をクリック・ドラッグするとその範囲に絞る。
3. **ハイライト**: 最初の兆候、影響の大きい対象（クリックで対象を絞る）、初めて出たイベント種別。
4. **時系列リスト**（縦）: 時刻、種別、レベル色、対象、タイトル、メッセージの抜粋。行を開くと詳細とイベント種別ガイド（`events/EventTypeGuideBody.tsx`）を表示し、次の操作を置く。
   - 「この対象で絞る」「ここを起点にする」
   - 「イベントで開く」「ログで開く」（`routing/correlationRange.ts` の `correlationHash` / `logsAroundEvent` を再利用）
   - 「グラフで開く」（既存の `onOpenSnapshotInMetrics` と同じ経路を一般化する）
5. **スナップショット**: 画面下部の折りたたみに移す。

その他:

- 時刻は `datetime/formatIsoInTimeZone.ts` と `useTimeZone` で、他のタブと同じタイムゾーン設定に揃える。
- 条件を URL に持たせる: `#/timeline?from=&to=&anchor=&vcenter_id=&entity=`。`correlationRange.ts` を `timeline` にも対応させ、`entity` と `anchor` を追加する（`parseAppHash` は `?` 以降を既に無視している）。
- 色とスペーシングは `styles/variables.css` のトークンを使う。
- 旧 `TimelineFilters.tsx` / `TimelineResults.tsx` / `useTimelinePanelController.ts` は新しい実装に置き換える。`panels/chat/IncidentTimelinePanel.tsx` はチャットのプレビュー用に残す。

### 3. 他のタブからの入口

各行に「タイムラインで見る」を追加し、起点の時刻 ±30 分と対象を URL で渡す。

- 通知履歴: `panels/alerts/AlertHistoryPanel.tsx`（通知時刻と対象）
- イベント: `panels/events/EventsPanel.tsx`（発生時刻と `entity_name`）
- 概要: `panels/summary/SummaryPanel.tsx`（要注意イベント、高負荷ホスト）

### 4. スナップショットに結果を保存する

- `IncidentTimelineManualSnapshot` に `result_payload`（JSON、NULL 可）を追加する（Alembic マイグレーション）。
- 保存時にサーバ側で `view` を実行し、その結果を保存する（クライアントから結果を送らせない）。
- 開くときは保存済みの結果を表示し、「保存時点の内容」と明示する。`result_payload` が NULL の旧データは、`from` / `to` / `vcenter_id` を新しいリクエストに写して再集計する。
- アラート発火時の自動スナップショット（`services/incident_timeline_snapshot.py` の `persist_alert_rule_firing_snapshot`）は、まず条件のみのままにする。評価処理の中で重い集計を走らせないため。結果の保存が必要かは PR5 で判断する。
- スナップショットの保持期間（`jobs/scheduler.py` の `purge_old_incident_timeline_snapshots`）がイベントの保持期間より長いことを確認し、短ければ設定を見直す。

### 5. チャットへの引き継ぎ（operator 以上）

「この範囲をチャットで分析」で、表示中の期間と vCenter をチャットタブに渡す（`useChatPanelController.ts` の期間の初期値に反映）。

## PR の分割

実装前に、この計画を `docs/plans/2026-11-15-timeline-triage-redesign.md` として保存し、正本にする。各 PR は TDD（失敗するテストを先に書く）で進め、ブランチを切って作業する。

| PR | 内容 | 主なファイル |
|---|---|---|
| PR1 | `view` API（event・alert・overview・highlights） | `routes/incident_timeline.py`、`services/incident_timeline_view.py`、`schemas/incident_timeline_view.py`、`tests/test_incident_timeline_view_api.py` |
| PR2 | 新しい画面（条件バー・俯瞰・ハイライト・リスト・タイムゾーン・URL・自動読み込み）。スナップショットは折りたたみへ | `panels/timeline/*`、`hooks/useTimelineViewController.ts`、`routing/correlationRange.ts`、`api/schemas/` |
| PR3 | 他のタブからの入口と、イベント・ログ・グラフへの出口 | `AlertHistoryPanel.tsx`、`EventsPanel.tsx`、`SummaryPanel.tsx`、`App.tsx` |
| PR4 | メトリクスの超過区間とログを `view` に追加 | `services/incident_timeline_view.py`、`panels/timeline/*` |
| PR5 | スナップショットの結果保存（マイグレーション） | `db/models.py`、`alembic/versions/`、`routes/incident_timeline.py`、`panels/timeline/*` |
| PR6 | チャットへの引き継ぎ、ユーザーガイド `docs/userguide/timeline.md`、ヘルプ（`help/tabHelpContent.ts`）、スクリーンショットの再取得 | `docs/`、`frontend/e2e/screenshots.spec.ts` |

PR1〜PR3 が終わった時点で、4 つの起点すべてから個々のイベントとアラートに辿れるようになる。PR4 以降は順番を入れ替えられる。

## 進め方とモデルの割り当て

メインのセッション（Fable）はアドバイザに徹し、実装とレビューはサブエージェントに任せる。

| 役割 | モデル | 担当 |
|---|---|---|
| アドバイザ | Fable（メインのセッション） | 各 PR の作業指示書の作成（対象ファイル、再利用する関数、テスト観点、完了条件）、実装中の設計上の質問への回答、レビュー指摘の採否の判断、PR 作成前の最終確認。コードは書かない |
| 実装（標準） | Sonnet | 既定の実装担当 |
| 実装（複雑） | Opus | 集計・まとめのロジックなど、設計判断を伴う実装 |
| 実装（単純作業） | Haiku | 同じ形の繰り返しや文言・ドキュメントの更新 |
| レビュー | Opus（`critic` エージェント） | PR ごとに差分をレビューする。実装したエージェントとは別に起動する |

PR ごとの割り当て:

| PR | 実装 | 理由 |
|---|---|---|
| PR1 | Opus（サービス層）、Sonnet（スキーマ・ルート・テストの土台） | 連続イベントのまとめ、alert の対象解決、ハイライトの算出に設計判断がある |
| PR2 | Sonnet | 画面の規模は大きいが、既存のパターン（コントローラのフック、recharts、タイムゾーン）に沿う |
| PR3 | Sonnet（`App.tsx` の遷移の一般化）、Haiku（3 つのパネルへのリンク追加） | リンク追加は同じ形の繰り返し |
| PR4 | Opus | 超過区間の算出とログのまとめ |
| PR5 | Sonnet | マイグレーションと保存・読み込みの経路 |
| PR6 | Sonnet（チャットへの引き継ぎ）、Haiku（ユーザーガイド・ヘルプ文言） | ドキュメントは単純作業 |

各 PR の流れ: アドバイザが指示書を出す → 実装エージェントが TDD で実装し、テストと lint を通す → Opus がレビュー → 指摘を実装エージェントが直す → アドバイザが最終確認 → PR を作成する。実装エージェントは PR ごとに git worktree で分離する。

## 対象外

- チャットの LLM 用コンテキスト（`chat_context_payloads.py` など）の変更
- 根本原因の自動推定や相関分析（`new_event_types` の比較まで）
- 旧 `POST /api/incident-timeline` の削除（旧スナップショットが参照しなくなってから別途）

## 検証

- バックエンド: `uv run pytest tests/test_incident_timeline_view_api.py tests/test_incident_timeline_api.py tests/test_incident_timeline_snapshot.py`。観点は、連続イベントのまとめ、alert の対象解決、超過区間の開始・終了、`truncated`、空の期間、`entity` 絞り込み、503 / 422、viewer 権限（`tests/test_route_policy.py`）。
- フロントエンド: `cd frontend && npm test -- timeline` と `npm run lint`、`npm run build`。観点は、URL からの復元、タイムゾーン表示、俯瞰からの絞り込み、行の展開と各リンクの遷移先、旧スナップショットの読み込み。
- 実機: モックモード（`docs/development/mock-mode.md`）で起動し、通知履歴 →「タイムラインで見る」→ 対象で絞る →「イベントで開く」の流れを通す。URL を別タブで開いて同じ表示になることを確認する。
- マイグレーション（PR5）: `tests/test_db_session_migrations.py` と、旧データ（`result_payload` が NULL）の読み込み。
