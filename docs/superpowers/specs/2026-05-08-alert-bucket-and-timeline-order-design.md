# Alert Bucket And Timeline Order Design

**Goal:** アラートをバケット単位で可視化し、イベント・メトリクスと同一時系列で相関確認できるようにする。あわせてタイムラインタブで時刻の昇順/降順を切り替え可能にする。

**Architecture:** 既存のイベント時系列バケット集計を拡張し、同一バケット内でアラートの上位N種別（スコア優先）とその他件数を返す。フロントはこの集計を `IncidentTimelineEntry(kind="alert")` へ展開し、並び順トグルは表示順のみを切り替える。`N` と並び順はタイムラインタブ専用の localStorage に保存する。

**Tech Stack:** Python (FastAPI, SQLAlchemy), TypeScript (React, Zod, Vitest)

---

## 要件確定

- アラートは `event_type` 集約の最終時刻1点表示ではなく、**各バケットごとに集計して表示**する。
- バケット内のアラート表示粒度は **上位N種別 + その他**。
- 上位判定は件数順ではなく **max notable score 高い順**（同点は件数降順、最後に event_type 昇順）。
- `N` はユーザー指定可能で、**タイムラインタブ専用に localStorage 保存**する。
- 時刻並び順はタイムラインタブで **昇順/降順切り替え**可能にする（こちらも localStorage 保存）。

## データフロー

1. `TimelinePanel` で期間・閾値・`alert_top_n` を指定して `/api/incident-timeline` を呼ぶ。
2. バックエンドのバケット集計が、各バケットについて以下を返す。
   - イベント件数（既存）
   - アラート上位N種別（新規）
   - 上位外合算件数（新規）
3. `chat_context_payloads` がこれを `IncidentTimelineEntry(kind="alert"|"event"|"metric")` へ展開。
4. `IncidentTimelinePanel` が並び順トグル状態に応じて列の表示順を決定し描画。

## バックエンド設計

### 1) バケット集計拡張（推奨案）

- 対象: `src/vcenter_event_assistant/services/chat_event_time_buckets.py`
- 既存 `EventTimeBucketRow` を拡張:
  - `alert_top_types: list[AlertTypeBucketRow]`（新規）
  - `alert_other_count: int`（新規）
- 新規モデル `AlertTypeBucketRow`:
  - `event_type: str`
  - `count: int`
  - `max_notable_score: int`

### 2) 集計ロジック

- 同一クエリ結果（`EventRecord`）からバケット別に:
  - イベント件数（既存）
  - アラート候補（`notable_score >= top_notable_min_score`）を event_type 単位で集約
- アラート上位N選定キー:
  1. `max_notable_score` 降順
  2. `count` 降順
  3. `event_type` 昇順
- 上位N以外は `alert_other_count` に合算。

### 3) タイムライン展開

- 対象: `src/vcenter_event_assistant/services/chat_context_payloads.py`
- 現在の `ctx.top_notable_event_groups` ベース `kind="alert"` 追加を廃止し、バケット集計から alert エントリを作る。
- タイトル例:
  - `vim.event.UserLogoutSessionEvent (20件, max score=87)`
  - `その他アラート (12件)`

## フロントエンド設計

### 1) リクエスト拡張

- 対象: `frontend/src/api/schemas.ts`
- `incidentTimelineBuildRequestSchema` に `alert_top_n`（int, min=1, max=20）を追加。

### 2) TimelinePanel UI

- 対象: `frontend/src/panels/timeline/TimelinePanel.tsx`
- 追加 UI:
  - `alert_top_n` 数値入力（1..20）
  - 並び順切替（`desc` / `asc`）
- localStorage key（案）:
  - `timelineAlertTopN`
  - `timelineSortOrder`

### 3) IncidentTimelinePanel 表示

- 対象: `frontend/src/panels/chat/IncidentTimelinePanel.tsx`
- 並び順を props で受け取り、`orderedColumns` を昇順/降順切替。
- 表示期間が複数日なら開始時刻に日付を含める既存修正を維持。

## エラーハンドリング

- `alert_top_n` が範囲外の場合は 422（バックエンドスキーマ）にする。
- フロントは不正入力をAPI送信前にクランプ/拒否し、`onError` で明示。
- localStorage 破損値はデフォルトへフォールバック（`N=3`, `order=desc`）。

## テスト戦略（TDD）

### バックエンド

- `tests/test_chat_event_time_buckets.py`（新規または拡張）
  - バケットごとに alert 上位N・その他が正しく算出される
  - 並び順キー（score > count > event_type）が守られる
- `tests/test_incident_timeline_api.py`
  - `alert_top_n` ありレスポンスで alert エントリが各バケットに出る
  - `alert_top_n` 範囲外で 422

### フロントエンド

- `frontend/src/api/schemas.test.ts`
  - `alert_top_n` の受理/拒否
- `frontend/src/panels/timeline/TimelinePanel.test.tsx`
  - `alert_top_n` と並び順が送信・保存・復元される
- `frontend/src/panels/chat/IncidentTimelinePanel.test.tsx`
  - 昇順/降順切替の描画順
  - 複数日表示時の開始日付付きヘッダ維持

## 実装順序

1. バックエンド集計モデル・ロジック拡張（RED→GREEN）
2. APIスキーマ・エンドポイント接続更新（RED→GREEN）
3. フロント request schema / TimelinePanel入力追加（RED→GREEN）
4. IncidentTimelinePanel 並び順切替対応（RED→GREEN）
5. 結合テストと回帰確認（pytest + vitest + build）

## 非スコープ

- チャットタブ側への並び順切替UI追加
- 全体設定タブへの統合
- 既存イベント/メトリクスのタイトルフォーマット変更

