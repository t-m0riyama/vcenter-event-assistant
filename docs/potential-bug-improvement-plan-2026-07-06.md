# 潜在不具合の改善プラン（2026-07-06）

[potential-bug-report-2026-07-06.md](potential-bug-report-2026-07-06.md) の指摘への対応計画。フェーズは「壊れているものを直す → 誤動作を防ぐ → 運用品質を上げる」の順で、各項目は独立して PR 化できる粒度にしてある。

**2026-07-07 更新:** `/grill-me` セッションで前提・優先順位・設計判断を確定し、本ドキュメントに反映した。

**2026-07-07 進捗追記（夜）:** フェーズ 2 完了。[#130](https://github.com/t-m0riyama/vcenter-event-assistant/pull/130)（M-3/M-7）・[#135](https://github.com/t-m0riyama/vcenter-event-assistant/pull/135)（M-6）を **main にマージ済み**。次は **フェーズ 3**（[#133](https://github.com/t-m0riyama/vcenter-event-assistant/issues/133)）。

**2026-07-07 進捗追記（深夜）:** フェーズ 3 — L-7/L-3 [#136](https://github.com/t-m0riyama/vcenter-event-assistant/pull/136)、L-1 [#137](https://github.com/t-m0riyama/vcenter-event-assistant/pull/137) を **main にマージ済み**。L-2/L-6（scheduler）を PR 作成中。

## 進捗状況（2026-07-07 時点）

| プラン | GitHub PR | Issue | 状態 | マージ日（UTC） | 備考 |
|--------|-----------|-------|------|-----------------|------|
| 1-1 H-1 | [#125](https://github.com/t-m0riyama/vcenter-event-assistant/pull/125) | — | **完了** | 2026-07-06 | `run_ingest_all`、`asyncio.Lock` + 409 |
| 1-3 H-4 | [#126](https://github.com/t-m0riyama/vcenter-event-assistant/pull/126) | — | **完了** | 2026-07-06 | per-host try/except |
| 1-4 H-3 | [#126](https://github.com/t-m0riyama/vcenter-event-assistant/pull/126) | — | **完了** | 2026-07-06 | `to_thread` + SMTP timeout |
| 1-5 M-2 | [#126](https://github.com/t-m0riyama/vcenter-event-assistant/pull/126) | — | **完了** | 2026-07-06 | カーソル後退防止 |
| 1-2 H-2 | [#127](https://github.com/t-m0riyama/vcenter-event-assistant/pull/127) | — | **完了** | 2026-07-06 | vCenter 分離、`stale`、Alembic |
| 2-1 M-1/M-5/M-4 | [#128](https://github.com/t-m0riyama/vcenter-event-assistant/pull/128) | — | **完了** | 2026-07-07 | commit 後通知、`channel=none` |
| 2-2 M-3/M-7 | [#130](https://github.com/t-m0riyama/vcenter-event-assistant/pull/130) | [#132](https://github.com/t-m0riyama/vcenter-event-assistant/issues/132) | **完了** | 2026-07-07 | key 欠落スキップ、max_pages ログ |
| 2-3 M-6 | [#135](https://github.com/t-m0riyama/vcenter-event-assistant/pull/135) | [#131](https://github.com/t-m0riyama/vcenter-event-assistant/issues/131) | **完了** | 2026-07-07 | 履歴・ダイジェスト・スナップショットパージ |
| 3-2 L-3 / 3-6 L-7 | [#136](https://github.com/t-m0riyama/vcenter-event-assistant/pull/136) | [#133](https://github.com/t-m0riyama/vcenter-event-assistant/issues/133) | **完了** | 2026-07-07 | `spa_fallback` 修正、rate-series 422 |
| 3-3 L-1 | [#137](https://github.com/t-m0riyama/vcenter-event-assistant/pull/137) | [#133](https://github.com/t-m0riyama/vcenter-event-assistant/issues/133) | **完了** | 2026-07-07 | digest `ok_llm_failed`、UI バッジ |
| 3-1 L-2 / L-6 | （PR 作成中） | [#133](https://github.com/t-m0riyama/vcenter-event-assistant/issues/133) | **レビュー待ち** | — | misfire_grace、digest try 統一 |
| フェーズ 3 残り | — | [#133](https://github.com/t-m0riyama/vcenter-event-assistant/issues/133) | **未着手** | — | L-4, L-5 |
| Backlog | — | [#134](https://github.com/t-m0riyama/vcenter-event-assistant/issues/134) | **追跡中** | — | 先送り項目 |

**フェーズ 1 + 2: 完了。** フェーズ 3 は #137 まで完了、L-2/L-6 を PR 中。

### マージ済み PR の実装メモ

- **#125（H-1）**: `services/ingest_runner.py` の `run_ingest_all`、スケジューラ・`POST /api/ingest/run` から共通利用。
- **#126（H-4 / H-3 / M-2）**: `collectors/perf.py`、`email_channel.py`（`to_thread`）、`ingestion.py`（カーソル）。CI 修正: `test_perf_sampling.py` に `connectionState=connected`。
- **#127（H-2）**: `alert_eval_metric.py` の `(vcenter_id, entity_moid)` パーティション、`metric_context_key`、`stale` 遷移・初回通知。移行 `q7r8s9t0u1v2`。
- **#128（M-1 / M-5 / M-4）**: `PendingAlertNotification` キュー、`_deliver_notification`、`AlertHistory.success` nullable。SMTP 未設定は `channel=none` / UI「未送信」。移行 `r8s9t0u1v2w3`。
- **#130（M-3 / M-7）**: `normalize_event` が `key` 欠落時スキップ + WARNING。`max_pages` 到達 WARNING。`tests/test_events_collector.py`（8 件）。
- **#135（M-6）**: `purge_retention` に `AlertHistory` / `DigestRecord` / `IncidentTimelineManualSnapshot` を追加。`ALERT_HISTORY_RETENTION_DAYS`（90）等、`0` で無効。`tests/test_retention.py` 拡張（+4 件）。
- **#136（L-3 / L-7）**: `is_spa_fallback_reserved_path()`、`EVENT_RATE_MAX_BUCKETS`（既定 5000）。
- **#137（L-1）**: digest `ok_llm_failed`、`digestStatusDisplay` バッジ、旧行後方互換。

### 次のアクション

1. **フェーズ 3 継続**: L-4/L-5 は L-2/L-6 マージ後
2. **本番・ステージング**: Alembic upgrade、パージ設定の確認、#130 の WARNING ログ監視
3. **Backlog**: [#134](https://github.com/t-m0riyama/vcenter-event-assistant/issues/134) — 運用観測に応じて優先度判断

## 確定した前提（grilling）

| 項目 | 内容 |
|------|------|
| vCenter 数 | **6 台以上**（H-2 は早期対応・本番影響あり） |
| DB | **開発 SQLite / 本番 PostgreSQL** |
| 手動インジェスト | **現状未使用**。将来 API 分離時に脆弱な実装は避ける |
| 第 1 週 | **H-1（#125）マージ済み**。H-2（#127）も完了 |

## フェーズ 1: 明確なバグの修正（~2 週）

### 1-1. 取り込みオーケストレータ統一と `/api/ingest/run` 修正（H-1）— PR #1、第 1 週 ✅ **完了（#125）**

**見積り: 小。** 第 1 週はこの PR のみマージする。

- 共通オーケストレータ `run_ingest_all(settings)` を新設する（`services/ingestion.py` または `jobs/ingest_runner.py`）。
  - `_ingest_for_enabled_vcenters` を内部で利用し、スケジューラと同じ **vCenter 並列（Semaphore）・per-vCenter 失敗分離** に揃える。
  - 呼び出し元: `POST /api/ingest/run`、`poll_events`、`poll_perf`（将来 API 分離時もオーケストレータを薄く切るだけで済む）。
- `api/routes/ingest.py` で `Depends(get_app_settings)` 等から `Settings` を取得し、ルート独自ループを廃止する。
- **同時実行ガード**: プロセス内 `asyncio.Lock` を `run_ingest_all` で保持。実行中の再入は **409 Conflict**。スケジューラジョブも同じ lock を取得（取得できなければスキップ）。
  - **backlog**: uvicorn workers > 1 やレプリカ構成向けの **DB リース**（`IngestionState.locked_until` 等）。
- **テスト**: ルート経由（TestClient + collectors をモック）の統合テストを追加。`settings` 欠落の退行を検出する。

**Done 条件:** `settings` 欠落解消、スケジューラと同等の並列・失敗分離、Lock 動作、ルート統合テストが緑。

### 1-2. metric_threshold 評価に `vcenter_id`・鮮度上限・`stale` 状態を導入（H-2）— PR #2、第 2 週〜 ✅ **完了（#127）**

**見積り: 大**（`stale` 状態・UI・移行を含む）。H-1 マージ後に単独 PR で着手する。

- `row_number()` の `partition_by` を `(vcenter_id, entity_moid)` に、`AlertState.context_key` を `"{vcenter_id}:{moid}"` 形式に変更する。
- **データ移行（Alembic）**: 判別可能な旧 `context_key` は書き換え、**判別不能な行は `resolved` 化**。移行直後に評価ジョブを 1 回実行する手順をデプロイドキュメントに追記する。
- **鮮度**: `sampled_at >= now - staleness_window`（設定値。例: `perf_sample_interval_seconds * 3`）より古いサンプルは評価対象から除外する。
- **鮮度切れ時の state**: 新状態 **`stale`** を導入する（`resolved` とは区別）。UI バッジ・集計（`resolutions` / `stale` カウント）を更新する。
- **`stale` 通知**: `firing` → `stale` への遷移は **初回のみ通知**し、以降は cooldown と同様に抑制する。
- **テスト**: 2 vCenter で同一 moid のケース、収集停止後に `stale` へ遷移するケース、初回 stale 通知のみ送られるケース。

### 1-3. ホストメトリクス収集の per-host 例外分離（H-4）— PR #3、H-2 と並行可 ✅ **完了（#126）**

**見積り: 小。**

- `perf.py` のホストループを try/except で囲み、失敗ホストは `logger.exception` してスキップ（データストア収集と同じポリシー）。
- `_host_metrics` で `runtime.connectionState` が connected 以外、または `quickStats` が None のホストを明示的にスキップする。
- **テスト**: 1 ホストが例外を投げても他ホストのサンプルが返ることを確認。

### 1-4. SMTP 送信の非同期化とタイムアウト（H-3）— PR #4、H-2 と並行可 ✅ **完了（#126）**

**見積り: 小。**

- 最小修正: `smtplib` 呼び出し全体を `asyncio.to_thread` に包み、`smtplib.SMTP(host, port, timeout=10)` を指定する（設定値化: `SMTP_TIMEOUT_SECONDS`）。
- 中期: `aiosmtplib` への移行（コード中の TODO コメントとも整合）。まずは最小修正を先行させる。
- **backlog**: スレッドプール飽和時の専用 executor や送信キュー。

### 1-5. 取り込みカーソルの後退防止（M-2）— PR #5、H-2 と並行可 ✅ **完了（#126）**

**見積り: 小。** フェーズ 1 後半に前倒し（元フェーズ 2 の 2-2）。

- 読み出し時の `-1 秒` 補正はフェッチ用のローカル変数に留め、書き戻しは「補正前のカーソル値」または `max_ts` のみとする（`max_ts is None` のときはカーソルを更新しない、が最も単純）。
- **テスト**: 空フェッチを複数回繰り返してもカーソルが後退しないこと。

## フェーズ 2: 誤動作・データ不整合の防止（~2-3 週）

### 2-1. アラート評価のトランザクション/通知順序の整理（M-1, M-5, M-4 ドキュメント）— PR #6 ✅ **完了（#128）**

**見積り: 中（設計変更）。**

- 設計変更: 評価ループを「state 変更を commit → その後に通知・スナップショット・履歴を記録」の 2 段階に分離する。
  - 評価関数は「発火/解消/`stale` 遷移した state のリスト」を返すだけにし、通知は `evaluate_all` 側で外側セッションを閉じた後に実行する。ネストした `session_scope` を解消する。
- **通知失敗時**: commit 済み state に対しメール送信が失敗した場合は **AlertHistory に失敗を記録するのみ**（再送は手動）。再送キューは **backlog**。
- `AlertHistory` に「送信スキップ（SMTP 未設定）」を表す値を導入する（例: `channel="none"` / `success=None` / `error_message="smtp not configured"`）。UI の履歴表示も対応する。
- **event_score（M-4）**: **自動 resolve は実装しない**（イベントは点発生のため）。`docs/backend-operations.md` と UI 文言に明記し、`AlertEvalSummary.resolutions` に注記する。自動 resolve 実装は **backlog**。
- **テスト**:
  - CI: SQLite バックエンドで評価→通知→履歴の統合テスト。
  - 本番相当: **ステージング PostgreSQL での手動チェックリスト**を `docs/backend-operations.md` に追記する（CI PostgreSQL 追加は **backlog**）。

### 2-2. `vmware_key` 欠落イベントとフェッチ上限ログ（M-3, M-7）— PR #7 ✅ **完了（#130）**

**見積り: 小。**

- `key` が取得できないイベントは **`vmware_key=0` に潰さず、挿入をスキップして WARNING ログ**を出す（観測待ちは行わず先行実装）。✅
- フェッチ上限到達時（M-7）に `logger.warning("event fetch hit max_pages ...")` を追加する。✅
- **テスト**: `tests/test_events_collector.py`（8 件）。✅
- **backlog**: ログで key 欠落の頻度が高い場合、`vmware_key` nullable + 代替ユニークキー（`(vcenter_id, occurred_at, event_type, message)` ハッシュ等）の本対応。

### 2-3. 履歴系テーブルの保持期間パージ（M-6）— PR #8 ✅ **完了（#135）**

**見積り: 小。**

- `purge_retention` ジョブに `AlertHistory`（例: 既定 90 日）、`DigestRecord`（既定 365 日）、インシデントタイムラインスナップショット（既定 90 日）の削除を追加。保持日数はそれぞれ Settings 化し、`0`（無効=無期限）を許可する。✅
- `.env.example` と `docs/backend-operations.md` に追記。✅

## フェーズ 3: 運用品質・堅牢性（順次）⏳ **進行中**（4/6 完了、L-2/L-6 PR 中）

### 3-1. スケジューラ設定の見直し（L-2, L-6) ✅ **PR 作成中**

- `_job_options_for_interval` / `_job_options_for_cron` で `misfire_grace_time` を付与（interval は間隔の半分、digest cron は 3600 秒）。✅
- digest ジョブの TZ 解決・ウィンドウ計算を try 内へ移動し、他ジョブと同じ「例外はログして継続」ポリシーに統一。✅

### 3-2. `get_event_rate_series` の入力ガード（L-3）✅ **完了（#136）**

- API 層で `(to - from) / bucket_seconds` に上限（`EVENT_RATE_MAX_BUCKETS`、既定 5,000）を設け、超過時は 422 を返す。✅
- 返り値アノテーション `any` → `Any` の修正。✅

### 3-3. digest の LLM 失敗を status で区別（L-1）✅ **完了（#137）**

- `status` に `ok_llm_failed` を追加（テンプレ成功・LLM 失敗時）。✅
- フロントの一覧・詳細でバッジ表示。旧行は `status=ok` + `error_message` でも `ok_llm_failed` と表示。✅

### 3-4. `EncryptedString` の Settings 依存の緩和（L-4）

- 鍵の解決を「bind 済み Settings → 環境変数 `VEA_SECRET_KEY` 直読み」のフォールバック付きヘルパーに切り出し、Alembic・スクリプト文脈でも動作するようにする。
- `enc:` 誤判定は現状の API バリデーションで実用上足りるため、ドキュメント注記のみとする。

### 3-5. SQLite 運用の明文化と緩和（L-5）

- `docs/getting-started.md` / `backend-operations.md` に「SQLite は小規模・単一ノード向け。vCenter 多数・本番は PostgreSQL 推奨」を明記。
- 取り込みの 1 トランザクション肥大を避けるため、イベント挿入を N 件（例: 500）ごとに commit する分割を検討（カーソル更新は最後に 1 回）。

### 3-6. `spa_fallback` のプレフィックス判定修正（L-7）✅ **完了（#136）**

- `is_spa_fallback_reserved_path()` を新設し、`full_path == "api" or full_path.startswith("api/")` に修正（`apidocs.html` 等の誤判定を防止）。✅

## 実施順序まとめ

| PR | 週 | 項目 | レポート | 見積り | 状態 |
|----|-----|------|----------|--------|------|
| #1 / [#125](https://github.com/t-m0riyama/vcenter-event-assistant/pull/125) | 1 | 1-1 取り込みオーケストレータ + `/api/ingest/run` | H-1 | 小 | ✅ |
| #2 / [#127](https://github.com/t-m0riyama/vcenter-event-assistant/pull/127) | 2〜 | 1-2 metric_threshold（vcenter 分離・鮮度・`stale`） | H-2 | **大** | ✅ |
| #3 / [#126](https://github.com/t-m0riyama/vcenter-event-assistant/pull/126) | 2〜 | 1-3 per-host 例外分離 | H-4 | 小 | ✅ |
| #4 / [#126](https://github.com/t-m0riyama/vcenter-event-assistant/pull/126) | 2〜 | 1-4 SMTP to_thread + timeout | H-3 | 小 | ✅ |
| #5 / [#126](https://github.com/t-m0riyama/vcenter-event-assistant/pull/126) | 2〜 | 1-5 カーソル後退防止 | M-2 | 小 | ✅ |
| #6 / [#128](https://github.com/t-m0riyama/vcenter-event-assistant/pull/128) | 3〜 | 2-1 通知順序・履歴正確化・M-4 ドキュメント | M-1, M-5, M-4 | 中 | ✅ |
| #7 / [#130](https://github.com/t-m0riyama/vcenter-event-assistant/pull/130) | 3〜 | 2-2 vmware_key 欠落・フェッチ上限ログ | M-3, M-7 | 小 | ✅ |
| #8 / [#135](https://github.com/t-m0riyama/vcenter-event-assistant/pull/135) | 3〜 | 2-3 履歴パージ | M-6 | 小 | ✅ |
| #9 / [#136](https://github.com/t-m0riyama/vcenter-event-assistant/pull/136) | 以降 | 3-2 / 3-6 rate-series・spa_fallback | L-3, L-7 | 小 | ✅ |
| #10 / [#137](https://github.com/t-m0riyama/vcenter-event-assistant/pull/137) | 以降 | 3-3 digest LLM 失敗 status | L-1 | 小 | ✅ |
| #11 / （PR 作成中） | 以降 | 3-1 scheduler misfire・digest try | L-2, L-6 | 小 | ⏳ |
| — / [#133](https://github.com/t-m0riyama/vcenter-event-assistant/issues/133) | 以降 | フェーズ 3 残り | L-4, L-5 | 小の集合 | ⏳ **次** |

```
週1     [PR#1 / #125] H-1 マージ済み ✅
週2〜    [PR#2 / #127] H-2 マージ済み ✅
         [PR#3-5 / #126] H-4, H-3, M-2 マージ済み ✅
週3〜    [PR#6 / #128] M-1/M-5/M-4 マージ済み ✅
         [PR#7 / #130] M-3/M-7 マージ済み ✅
         [PR#8 / #135] M-6 マージ済み ✅  ← フェーズ2 完了
         [PR#9 / #136] L-3/L-7 マージ済み ✅
         [PR#10 / #137] L-1 マージ済み ✅
         [PR#11] L-2/L-6 PR 中
以降     [Issue #133] L-4 → L-5 + [Issue #134] backlog
```

## Backlog（grilling で明示的に先送り）

| 項目 | 内容 |
|------|------|
| ingest DB リース | multi-worker / レプリカ向けの同時実行ガード |
| CI PostgreSQL | M-1 統合テストの本番 DB 再現（暫定はステージング手動） |
| event_score 自動 resolve | lookback 内に該当イベントがなくなったら `resolved` |
| 通知再送キュー | commit 後の SMTP 失敗に対する非同期リトライ |
| `vmware_key` 本対応 | nullable + 代替ユニークキー（頻度が高い場合） |
| SMTP 専用 executor | `to_thread` 飽和対策 |
| `aiosmtplib` 移行 | H-3 中期 |

## 共通の進め方

- 修正前に不具合を再現する失敗テストを先に書く（特に H-1 のようにテストの死角で発生したものは、同じ層のテストを必ず追加する）。
- H-2 / 2-1 のようにスキーマ・設計に触れるものは Alembic マイグレーションと `docs/` 更新をセットにする。
- 新設する設定値（SMTP タイムアウト、鮮度ウィンドウ、履歴保持日数、バケット上限）はすべて `.env.example` に既定値と説明を追記する。
- **フェーズ 3** は #137 まで完了。L-2/L-6（scheduler）を PR 中（[#133](https://github.com/t-m0riyama/vcenter-event-assistant/issues/133)）。
