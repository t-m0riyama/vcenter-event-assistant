# アラート連動スナップショット設計

## Goal

- **タイムライン生成**（`POST /api/incident-timeline`）では DB へスナップショットを保存しない（明示的 `POST /snapshots/manual` のみ）。
- **AlertRule の新規 firing**（スケジューラ `evaluate_alerts`）時に `snapshot_kind=auto` を保存し、後から同じ `build_request_payload` でタイムラインを再生成できるようにする。

## 非目標

- タイムライン JSON 上の自動トリガー行（`critical_burst` 等）の削除
- 既存 DB 内の過去 auto 行の削除
- `graph_context` の自動付与

## データフロー

1. オペレータがタイムラインを生成 → レスポンス JSON のみ（`kind=alert` 表示は可）
2. オペレータが「スナップショットを保存」→ `snapshot_kind=manual`
3. `AlertEvaluator` がルールを評価し firing → `_notify` 内で auto スナップショット 1 件（重複キーはスキップ）→ メール・`AlertHistory`

## 契約

| 項目 | 値 |
|------|-----|
| `trigger_id` | `alert_rule_{rule_id}_{context_slug}` |
| `trigger_evidence.trigger_type` | `alert_rule` |
| 重複防止 | `(auto, trigger_id, from_time, to_time, timestamp_utc)` |
| 期間 | `from = fired_at - alert_snapshot_lookback_hours`、`to = now(UTC)` |
| resolved | スナップショット保存しない |

## 実装参照

- [`incident_timeline_snapshot.py`](../../../src/vcenter_event_assistant/services/incident_timeline_snapshot.py)
- [`alert_eval.py`](../../../src/vcenter_event_assistant/services/alert_eval.py) の `_notify`
- 実装プラン: [`../plans/2026-05-22-alert-driven-snapshot.md`](../plans/2026-05-22-alert-driven-snapshot.md)
