# アラート手動解消・履歴削除 — 設計

**Goal:** イベントスコア型の発火中アラートを手動で解消（回復メール送信）し、通知履歴の行を個別に削除できるようにする。

**Architecture:** `AlertEvaluator` に手動解消メソッドを追加し、既存 `_notify` 経路で回復通知を送る。`GET /api/alerts/history` に `rule_type` と `can_resolve` を付与。通知履歴パネルに解消・削除ボタンを追加。

**Tech Stack:** Python 3.12+ (FastAPI, SQLAlchemy), pytest。フロントは React (TypeScript)。

**承認:** 2026-07-04

---

## 要件

| ID | 要件 |
|----|------|
| R1 | **解消**: `event_score` 型のみ。`AlertState` を `resolved` にし、回復メールと `AlertHistory` 行を追加する。 |
| R2 | **削除**: `AlertHistory` の指定行 1 件のみ削除。`AlertState` は変更しない。 |
| R3 | UI は通知履歴の各行に **解消** と **削除** を別ボタンで配置する。 |
| R4 | 解消ボタンは `rule_type == event_score` かつ当該 `(rule_id, context_key)` が **現在 firing** のときのみ表示。 |
| R5 | メトリクス閾値型は手動解消の対象外（自動回復のみ）。 |
| R6 | 利用者向け `docs/user-guides/alerts.md` を更新する。 |

## 非目標

- メトリクス閾値型の手動解消
- 履歴の一括削除
- 解消時のメール送信オプション（常に送信）

## API

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/alerts/states/resolve` | body: `{ rule_id, context_key }` → 204 |
| `DELETE` | `/api/alerts/history/{history_id}` | 履歴 1 行削除 → 204 |

`GET /api/alerts/history` の各 item に `rule_type`, `can_resolve` を追加。

## 注意事項（ドキュメント記載）

- 解消後も評価ウィンドウ内に閾値以上のイベントがあれば再発火しうる。
- 履歴削除は見た目の整理のみ。`firing` 状態は解消ボタンで止める。
