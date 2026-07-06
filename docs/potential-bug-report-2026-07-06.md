# 潜在不具合レポート（2026-07-06）

バックエンド（`src/vcenter_event_assistant/`）を中心にコードレビューを行い、実行時に不具合として顕在化しうる箇所を洗い出した。フロントエンドは localStorage 系ユーティリティ・インポート処理をスポットチェックした範囲では防御的に書かれており、重大な問題は確認していない。

対応方針・優先順位は [potential-bug-improvement-plan-2026-07-06.md](potential-bug-improvement-plan-2026-07-06.md) を参照。

---

## 重大度: 高

### H-1. `/api/ingest/run` が必須引数欠落で常に 500 エラーになる

- 対象: `src/vcenter_event_assistant/api/routes/ingest.py:27,31`
- `ingest_events_for_vcenter` / `ingest_metrics_for_vcenter` のシグネチャは `(session, vcenter, *, settings: Settings)` でキーワード専用引数 `settings` が必須だが、ルート側は `settings` を渡していない。手動インジェスト API を呼ぶと `TypeError` で必ず失敗する。
- テスト（`tests/test_ingestion.py`）はサービス関数を直接 `settings=` 付きで呼んでいるため、このルートの退行を検出できていない。
- 併せて、この API には同時実行ガードがなく、スケジューラの定期ポーリング（`max_instances=1` はスケジュールジョブ間のみ有効）と同時に走ると `IngestionState` カーソルの更新が競合しうる。

### H-2. metric_threshold アラート評価が vCenter を区別せず、鮮度チェックもない

- 対象: `src/vcenter_event_assistant/services/alerting/alert_eval_metric.py:30-61`
- 最新サンプル抽出の `row_number()` が `entity_moid` のみでパーティションしており、`vcenter_id` を含まない。MoRef ID（例: `host-10`）は vCenter 間で衝突しうるため、複数 vCenter 環境では別 vCenter のホストのサンプルが混ざり、誤発火・発火漏れ・`AlertState.context_key` の衝突が起きうる。
- また「最新サンプル」に鮮度の上限がない。vCenter を無効化した／収集が止まった場合でも、何日も前の閾値超えサンプルを根拠にアラートが firing のまま固定される（resolve もされない）。

### H-3. アラートメール送信が同期 smtplib でイベントループをブロックする

- 対象: `src/vcenter_event_assistant/services/alerting/notification/email_channel.py:50-57`
- `async def notify` の中で `smtplib.SMTP(...)` を直接呼んでおり、`asyncio.to_thread` 等で逃がしていない。さらに `SMTP()` にタイムアウト未指定のため、SMTP サーバ無応答時は OS デフォルト（数十秒〜数分）までイベントループ全体（API 応答・他ジョブ含む）が停止する。コード中のコメントでも既知とされているが、アラート評価はデフォルト 60 秒間隔の常駐ジョブであり影響が大きい。

### H-4. ホストメトリクス収集が 1 ホストの異常で vCenter 全体分失敗する

- 対象: `src/vcenter_event_assistant/collectors/perf.py:86-88`, `_host_metrics`（同 27-59 行）
- ホストごとのループに per-host の例外分離がない（データストア収集のみ try/except あり）。切断状態・応答不能なホストで `summary.quickStats` 等の属性アクセスが例外を投げると、その vCenter のホストメトリクス収集がまるごと 0 件になる。障害時こそメトリクスが欲しいツールの性質上、影響が大きい。
- `quickStats` が None のケース（disconnected / notResponding ホスト）で `AttributeError` になる点も同根。

---

## 重大度: 中

### M-1. アラート評価中のネストした `session_scope()`（トランザクション整合性・SQLite での競合）

- 対象: `alert_eval_metric.py` / `alert_eval_event_score.py`（外側 `session_scope` 内から `deps.notify` を呼ぶ）→ `alert_eval.py:119-174`（`_notify` がさらに 2 つの `session_scope` を開く）
- 問題点は 2 つ:
  1. **通知が commit 前に走る**: `AlertState` の変更は外側セッションで flush のみの段階で、通知メール送信・スナップショット保存・履歴保存が先に確定する。外側トランザクションが最終的に rollback すると「通知は飛んだが state は変わっていない」不整合になる。
  2. **SQLite（StaticPool）では単一コネクションを共有**: `db/session.py:51-57` の StaticPool 構成では、外側トランザクションが開いたまま内側セッションが同じコネクション上でトランザクション操作を行い、`cannot start a transaction within a transaction` 系のエラーやロック異常を誘発しうる。PostgreSQL でも評価 1 回あたり最大 3 コネクションを同時消費する。

### M-2. イベント取り込みカーソルが空フェッチのたびに 1 秒ずつ後退する

- 対象: `src/vcenter_event_assistant/services/ingestion.py:54,107-108`
- 読み出し時に `since -= 1秒` してから、`max_ts` が None（新規イベントなし）の場合にその**減算済み**の値を `cursor_value` に書き戻している。イベントが来ない環境ではポーリングごとにカーソルが 1 秒ずつ過去に戻り続け、長期間ではウィンドウが際限なく広がる。重複挿入自体は ON CONFLICT で防がれるが、vCenter への問い合わせ範囲と転送量が無駄に増える。

### M-3. `vmware_key` 欠落イベントが key=0 に潰され、2 件目以降が暗黙に捨てられる

- 対象: `src/vcenter_event_assistant/collectors/events.py:88`、`services/ingestion.py:96`
- `normalize_event` は `key` 属性がないイベントを `vmware_key=0` に正規化する。一意制約が `(vcenter_id, vmware_key)` のため、key を持たないイベントは vCenter ごとに最初の 1 件しか保存されず、以降は ON CONFLICT DO NOTHING で無音で破棄される。取りこぼしがログにも現れない。

### M-4. event_score アラートが自動 resolve されない（`resolutions` が常に 0）

- 対象: `src/vcenter_event_assistant/services/alerting/alert_eval_event_score.py`
- 発火条件を満たさなくなっても state を `resolved` に戻すコードパスがなく、`resolutions` は常に 0。手動 resolve（`resolve_event_score_manually`）のみが解消手段。仕様として意図的なら、集計サマリやドキュメント上その旨を明示しないと「回復通知が来ない不具合」と区別できない。

### M-5. 通知未送信でも AlertHistory が `channel="email", success=True` で記録される

- 対象: `alert_eval.py:154-174` + `email_channel.py:33-39`
- SMTP 未設定時は `notify` が警告ログだけで正常 return するため、履歴上は「メール通知成功」として残る。監査・トラブルシュートの際に誤解を招く。

### M-6. DigestRecord / AlertHistory / スナップショットに保持期間パージがない

- 対象: `services/ingestion.py`（purge はイベントとメトリクスのみ）、`jobs/scheduler.py`
- 定期パージの対象は `EventRecord` / `MetricSample` だけで、`DigestRecord`・`AlertHistory`・インシデントタイムラインスナップショットは無期限に蓄積する。特に AlertHistory はアラート評価 60 秒間隔 × cooldown 再通知で長期運用では無視できない量になる。

### M-7. イベントフェッチの上限到達（100 ページ × 500 件）が無音

- 対象: `src/vcenter_event_assistant/collectors/events.py:61-65`
- 1 回のフェッチ上限は 50,000 件。上限に達した場合でもカーソルは取得済み分の max_ts に進むため次回に残りを拾える構造だが、上限到達を示すログが一切なく、イベントストーム時の取り込み遅延に運用側が気づけない。

---

## 重大度: 低

### L-1. `run_digest_once` が LLM 失敗時も `status="ok"` を返す

- 対象: `services/digest/digest_run.py:63-71`
- LLM 追記に失敗しても `error_message` に格納されるだけで status は `ok`。テンプレートのみのダイジェストとして成立しているなら妥当だが、`status` だけを見る監視・UI は失敗を検知できない。`ok_with_llm_error` 等の区別、または UI 側での error_message 表示の徹底が望ましい。

### L-2. digest ジョブのウィンドウ計算が try ブロック外

- 対象: `jobs/scheduler.py:119-186`
- `resolve_digest_timezone` / `zoned_*_window` の例外は捕捉されず APScheduler 側のログにしか出ない。他の処理と同じ「握りつぶしてログ」ポリシーに揃っていない。

### L-3. `get_event_rate_series` のバケット数が無制限

- 対象: `services/event_repository.py:66-74`
- `from/to` 期間と `bucket_seconds` の組み合わせを検証せずに全バケットをメモリ上に展開する。極端なパラメータ（長期間 × 1 秒バケット等）で応答遅延・メモリ消費が跳ねる。API 層でのバケット数上限が未確認なら追加が必要。あわせて返り値アノテーション `list[dict[str, any]]` は組み込み関数 `any` を型として使っており誤記（`Any`）。

### L-4. `EncryptedString` が bind 済み Settings に暗黙依存

- 対象: `db/encrypted_string.py:72,84`
- 型デコレータが `require_settings()` を呼ぶため、`bind_settings` を経ない文脈（単発スクリプト、Alembic のオフライン操作等）で vCenter 行に触れると実行時エラーになる。また DB 値が偶然 `enc:` で始まる平文だった場合に復号を試みてしまう（API 層のバリデーションで新規入力は防がれているが、DB 直接投入経路では防げない）。

### L-5. SQLite 構成は StaticPool の単一コネクションで全処理を直列化

- 対象: `db/session.py:51-57`
- API リクエスト・取り込み（並列度 3）・アラート評価が 1 コネクションを取り合う。`timeout: 30` で多くは緩和されるが、大きな取り込みトランザクション中は API 応答が待たされる。SQLite は小規模向けと割り切るなら、その旨の運用ドキュメント明記と、取り込みのバッチ commit 分割が緩和策になる。

### L-6. スケジューラの misfire 設定が未指定

- 対象: `jobs/scheduler.py:45`
- `coalesce=True, max_instances=1` のみで `misfire_grace_time` が既定（1 秒）。H-3 のようなイベントループ停止が起きると、digest の cron ジョブなど「その時刻に 1 回だけ」のジョブが丸ごとスキップされうる。

### L-7. `spa_fallback` のプレフィックス判定が広すぎる

- 対象: `main.py:121`
- `full_path.startswith("api")` は `apidocs.html` のような静的ファイル名まで 404 にする。実害はほぼないが `api/` 境界での判定が正確。

---

## 補足（不具合ではないが確認したもの）

- vCenter パスワードは `VCenterRead` に含まれず、API から漏れない（`api/schemas/vcenters.py`）。
- SPA フォールバックのパストラバーサルは `is_relative_to` で防御済み（`main.py:124-129`）。
- 週次 cron の APScheduler 曜日解釈（0=月曜）の罠は settings の description で明記済み。
- naive datetime の生成（`datetime.now()` / `utcnow`）は backend に見当たらず、tz-aware で統一されている。
- フロントエンドの localStorage 読み出しは破損データを削除するフォールバックを備えている。
