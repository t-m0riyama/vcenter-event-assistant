# アラート通知機能 設計ドキュメント

## 概要

イベントの `notable_score` 閾値やメトリクス（CPU/メモリ利用率）の閾値をもとに、リアルタイムでメール通知する機能を追加する。通知手段はまずメールに対応し、将来 Teams webhook にも拡張可能な設計とする。

## 要件

- **トリガー**: イベントの `notable_score` 閾値、メトリクス（CPU/メモリ）閾値の 2 種類
- **通知手段**: メール（SMTP）。将来 Teams webhook に拡張予定（今回はスコープ外）
- **評価タイミング**: 収集ジョブとは独立した専用スケジュールジョブで評価
- **ルール管理**: DB に保存し、フロントエンド UI から CRUD 操作
- **重複抑制**: 状態遷移方式（firing / resolved）。発火時に 1 回・回復時に 1 回のみ通知
- **宛先**: グローバルに 1 つ（カンマ区切りで複数指定可、全ルール共通）
- **テンプレート**: Jinja2。発火用・回復用で別ファイル。パッケージ同梱のデフォルト + 環境変数で外部パス上書き可能

## データモデル

### `alert_rules` — アラートルール定義

| カラム | 型 | 説明 |
|---|---|---|
| `id` | Integer PK | 自動採番 |
| `name` | String(255), unique | ルール名（例: "CPU高負荷アラート"） |
| `rule_type` | String(64) | `"event_score"` or `"metric_threshold"` |
| `is_enabled` | Boolean | 有効/無効 |
| `config` | JSON | ルール固有のパラメータ |
| `created_at` | DateTime(tz) | 作成日時 |

**`config` JSON の構造:**

- `event_score` 型: `{"min_notable_score": 60}`
- `metric_threshold` 型: `{"metric_key": "host.cpu.usage_pct", "threshold": 90.0}`

### `alert_states` — アラートの現在の状態

| カラム | 型 | 説明 |
|---|---|---|
| `id` | Integer PK | 自動採番 |
| `rule_id` | FK → alert_rules.id | 対象ルール |
| `state` | String(32) | `"firing"` or `"resolved"` |
| `context_key` | String(512) | 発火対象の識別子（event_type や host MOID 等） |
| `fired_at` | DateTime(tz) | 発火日時 |
| `resolved_at` | DateTime(tz), nullable | 回復日時 |

`context_key` により、同一ルールでも対象が異なれば別々に状態管理できる（例: ホスト A の CPU とホスト B の CPU は別のアラート状態）。

### `alert_history` — 通知履歴

| カラム | 型 | 説明 |
|---|---|---|
| `id` | Integer PK | 自動採番 |
| `rule_id` | FK → alert_rules.id | 対象ルール |
| `state` | String(32) | 通知時の状態（`"firing"` or `"resolved"`） |
| `context_key` | String(512) | 発火対象の識別子 |
| `notified_at` | DateTime(tz) | 通知日時 |
| `channel` | String(64) | `"email"`（将来: `"teams_webhook"`） |
| `success` | Boolean | 送信成功/失敗 |
| `error_message` | Text, nullable | 失敗時のエラー詳細 |

## バックエンド

### 環境変数（Settings）

```
# --- SMTP ---
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=user@example.com
SMTP_PASSWORD=secret
SMTP_USE_TLS=true
ALERT_EMAIL_FROM=noreply@example.com
ALERT_EMAIL_TO=ops-team@example.com,admin@example.com

# --- Alert Evaluation ---
ALERT_EVAL_INTERVAL_SECONDS=60
```

### 通知チャネル抽象化

```
services/
  notification/
    __init__.py
    base.py            # NotificationChannel ABC (send_firing / send_resolved)
    email_channel.py   # EmailChannel: SMTP でメール送信
    renderer.py        # Jinja2 テンプレートレンダリング
```

`base.py` に抽象クラスを定義し、`email_channel.py` で実装する。将来 `teams_webhook_channel.py` を追加するだけで拡張可能にする。

### アラート評価エンジン（`services/alert_eval.py`）

**評価フロー:**

1. 有効な `alert_rules` を全件取得
2. ルールタイプごとに現在の状態を評価:
   - **`event_score`**: 前回評価時刻以降の新規イベントで `notable_score >= min_notable_score` のものを検索
   - **`metric_threshold`**: 最新の `MetricSample` で `value >= threshold` のホストを検索
3. `alert_states` と比較して状態遷移を検出:
   - **新規発火**: 条件を満たすが `alert_states` にレコードがない → `firing` を INSERT → 発火通知送信
   - **継続中**: 条件を満たし `alert_states` が既に `firing` → 何もしない
   - **回復**: `alert_states` が `firing` だが条件を満たさなくなった → `resolved` に UPDATE → 回復通知送信
4. 通知結果を `alert_history` に記録

### スケジューラ統合

`scheduler.py` に通知評価ジョブを追加:

```python
scheduler.add_job(
    evaluate_alerts,
    "interval",
    seconds=settings.alert_eval_interval_seconds,
    id="alert_eval",
)
```

### API エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/api/alert-rules` | ルール一覧 |
| `POST` | `/api/alert-rules` | ルール作成 |
| `PATCH` | `/api/alert-rules/{id}` | ルール更新 |
| `DELETE` | `/api/alert-rules/{id}` | ルール削除 |
| `GET` | `/api/alert-history` | 通知履歴一覧（ページネーション） |

### Jinja2 テンプレート

```
templates/
  alert_firing.txt.j2     # 発火通知メール本文
  alert_resolved.txt.j2   # 回復通知メール本文
```

テンプレート管理はダイジェストと同じパターン:
- パッケージ同梱のデフォルトテンプレート
- 環境変数（`ALERT_TEMPLATE_FIRING_PATH` / `ALERT_TEMPLATE_RESOLVED_PATH`）で外部テンプレートパスを上書き可能

**テンプレートに渡すコンテキスト変数:**

- `rule` — ルール名・タイプ・設定値
- `context_key` — 対象の識別子
- `fired_at` / `resolved_at` — 発火/回復時刻
- `details` — 該当イベントやメトリクスの詳細情報（イベント種別、ホスト名、値など）
- `display_timezone` — 表示用タイムゾーン

## フロントエンド

### Settings > Alerts タブ（ルール管理）

Settings パネル内にサブタブとして追加。

- ルール一覧テーブル（名前、タイプ、有効/無効、現在の発火数）
- 「追加」ボタンからインラインフォームで新規作成
- 各ルールに「編集」「削除」ボタン
- 有効/無効のトグルスイッチ

### 「通知履歴」メインタブ（通知履歴）

Events / Metrics / Digest 等と同列のトップレベルタブ。ラベルは「通知履歴」。

- 発火 / 回復の履歴をテーブルで一覧表示
- カラム: 日時、ルール名、状態（firing / resolved）、対象（context_key）、チャネル、成功/失敗
- フィルタ: ルール名、状態、成功/失敗

## 将来の拡張

- **Teams webhook 通知**: `services/notification/teams_webhook_channel.py` を追加し、`NotificationChannel` を実装する
- **特定イベント種別トリガー**: `rule_type: "event_type_match"` を追加し、`config` に `{"event_types": ["HostConnectionLostEvent"]}` を持たせる
- **ルールごとの宛先設定**: `alert_rules` に `recipients` カラムを追加する
