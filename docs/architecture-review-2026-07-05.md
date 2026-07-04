# アーキテクチャレビューレポート（2026-07-05）

本レポートは、リポジトリの現状実装（バックエンド `src/vcenter_event_assistant/`、フロントエンド `frontend/src/`、CI・マイグレーション周辺）を確認し、アーキテクチャ上の課題と、改善により保守性向上が期待できる事項を整理したものである。改善の具体的な進め方は [architecture-improvement-plan-2026-07-05.md](architecture-improvement-plan-2026-07-05.md) を参照する。

## 総評

全体として、レイヤ分離（routes / schemas / services / collectors / db / jobs）が明確で、テストが充実（バックエンド 60+ テストファイル、フロントエンド Vitest カバレッジ + Playwright E2E）しており、健全な状態である。一方で、以下のカテゴリに保守面のリスクが蓄積しつつある。

- **スキーマ管理の二重化**（Alembic と `create_all` + 手書き列追加の併存）
- **セキュリティ上の既定値**（資格情報の平文保存、TLS 検証の恒久無効）
- **設定シングルトンへの広範な直接依存**
- **取り込み処理の N+1 パターン**（スケール限界）
- **`services/` のフラット化肥大**（30+ モジュールが接頭辞でドメイン分類されている）

---

## 課題一覧

### A. データベース・マイグレーション

#### A-1. スキーマ管理の二重化（重要度: 高）

`alembic/versions/` に 14 本のマイグレーションが存在する一方、起動時の `db/session.py::init_db()` は `Base.metadata.create_all` を実行し、さらに旧 DB 向けの列追加を手書き関数（`_ensure_events_user_comment_column`、`ensure_event_type_guides_action_required_column`、`_ensure_alert_states_last_notified_at_column`）で行っている。

- 列を 1 つ追加するたびに `session.py` に dialect 分岐（SQLite の `PRAGMA table_info` / PostgreSQL の `ALTER TABLE ... DEFAULT false`）を含む関数が増える構造で、既に 100 行規模に達している。
- Alembic のリビジョン履歴と実 DB の状態が対応しなくなる（`alembic_version` テーブルが正しく進まない DB が生まれる）ため、将来 Alembic に一本化する際の障壁が時間とともに大きくなる。
- `create_all` は既存テーブルを変更しないため、「モデル変更 → session.py にも ensure 関数を書く → Alembic にも書く」という三重メンテナンスが発生している。

#### A-2. 時系列クエリ向けの複合インデックス不足（重要度: 中）

`db/models.py` の `EventRecord` / `MetricSample` は単一列インデックス（`occurred_at`、`sampled_at`、`metric_key` など）のみで、主要なアクセスパターンである「vCenter × 期間」「vCenter × エンティティ × メトリクス × 期間」に対応する複合インデックスがない。保持期間が短い（既定 7 日）うちは顕在化しにくいが、保持期間を延ばす・vCenter 数が増える運用で一覧系 API とパージ処理の劣化要因になる。

#### A-3. 取り込みカーソルが文字列格納（重要度: 低）

`IngestionState.cursor_value` が ISO 文字列の `Text` で、`ingestion.py` 側で `datetime.fromisoformat` によるパースを行っている。型不整合はテストで守られているが、DB 上で比較・監視ができず、破損時の検知がアプリ層任せになる。

### B. セキュリティ（保守運用に直結するもの）

#### B-1. vCenter 資格情報の平文保存（重要度: 高)

`VCenter.password` が DB に平文で保存される。API 応答（`VCenterRead`）からは除外されており漏洩面は配慮されているが、DB ファイル・ダンプ・バックアップがそのまま資格情報の漏洩点になる。SQLite 運用ではファイル 1 つの流出で全 vCenter の管理者資格情報が失われる。

#### B-2. TLS 証明書検証が恒久的に無効（重要度: 高）

`collectors/connection.py` で `ssl.CERT_NONE` が固定されており、設定で有効化できない。検証ラボでは妥当な既定だが、本番で証明書検証を有効にする選択肢がなく、中間者攻撃に対して構造的に無防備である。vCenter ごと、または環境変数での opt-in すら存在しない点が課題。

#### B-3. API 認証なし（既知の制約、重要度: 情報）

README に「リバースプロキシで認証する」前提が明記されており設計判断としては整合している。ただし `/api/vcenters` の作成・更新（資格情報の登録）や `/api/ingest` まで無認証で到達できるため、リバースプロキシの設定ミスが即座に全権限の露出になる。最低限の静的 API トークン（オプション）があると多層防御になる。

### C. バックエンド構造

#### C-1. `get_settings()` シングルトンへの直接依存が 26 ファイルに分散（重要度: 中）

サービス層・ジョブ・ルートの多くが関数内で `get_settings()` を直接呼ぶ。`lru_cache` されているため:

- テストでは環境変数の差し替えとキャッシュクリアの組み合わせが必要になり、`VEA_PYTEST=1` のような特殊フラグ（`settings.py`）で回避している。
- 実行中の設定変更（将来の管理画面からの設定変更など）が構造的に不可能。
- 依存が暗黙的なため、各サービスがどの設定に依存しているかがシグネチャから読めない。

#### C-2. `services/` のフラット化肥大（重要度: 中）

`services/` 直下に 30 超のモジュールが並び、`chat_*`（8 本）、`digest_*`（6 本）、`llm_*`（7 本）、`alert_eval*`（5 本）という接頭辞でドメインを表現している。テストディレクトリも `tests/` 直下と `tests/services/`、`tests/api/routes/` が混在し始めている。ファイル数がこのペースで増えると、関連モジュールの発見コストと import 文の長大化が保守負荷になる。`services/notification/` のようにサブパッケージ化された例が既にあり、方針の不統一でもある。

#### C-3. `AlertEvaluator` の責務分割が中途半端（重要度: 低）

`alert_eval.py` の `AlertEvaluator` はファサードだが、実評価関数が `evaluate_event_score_rule(self, rule)` のように **evaluator 自身を第一引数に受け取る自由関数**として別モジュールに置かれている。実質的にはメソッドの外出しであり、依存（renderer / email_channel / session）が暗黙的に共有される。ルール種別の追加時にどこを触るべきかが読み取りにくい。

#### C-4. スケジューラジョブの定義スタイル混在と多重実行ガード不足（重要度: 中）

`jobs/scheduler.py` では、ダイジェスト系はモジュールレベル関数、`poll_events` / `poll_perf` / `purge` は `setup_scheduler` 内のクロージャと、定義スタイルが混在している。また:

- `coalesce=True` は `evaluate_alerts` のみで、`poll_events` / `poll_perf` は vCenter 応答が遅い場合に前回実行と重なり得る（`max_instances` 未指定、既定 1 のため APScheduler が warning を出してスキップするが、意図の明示がない）。
- パージ間隔（6 時間）がハードコードされている。
- 各 vCenter の取り込みが直列であり、1 台の応答遅延が全体のスケジュールを遅らせる。

#### C-5. 取り込み処理の N+1 SELECT（重要度: 中〜高）

`services/ingestion.py` は、イベント 1 件・メトリクスサンプル 1 点ごとに重複確認の `SELECT` を発行してから `INSERT` している。両テーブルとも一意制約（`uq_event_vcenter_vmware_key`、`uq_metric_sample_point`）が既にあるため、dialect の `INSERT ... ON CONFLICT DO NOTHING`（PostgreSQL / SQLite とも対応）に置き換えれば往復回数を 1/2 以下にでき、イベントバースト時（vCenter 障害時こそイベントが集中する）の取り込み遅延を防げる。現状は「障害時に最も負荷が上がる」特性がある。

#### C-6. レガシー設定の併存（重要度: 低）

`DigestSettingsMixin` に非推奨の `digest_scheduler_enabled` / `digest_cron` と新設定が併存し、`effective_digest_daily_*` プロパティで合成している。互換ロジック自体は妥当だが、削除期限やドキュメント上の移行案内がなく、恒久化するリスクがある。

### D. フロントエンド

#### D-1. タブ切替が条件レンダリング列挙で、状態がタブ離脱時に破棄される（重要度: 中）

`App.tsx` は 8 タブ + 設定 6 サブタブを `{tab === 'xxx' && ...}` の列挙で切り替えており、タブを離れるとパネルが unmount されてフィルタ・入力途中のコメント等のローカル状態が失われる（例: イベント一覧で絞り込み → チャットで質問 → 戻ると絞り込みが消える）。またタブ追加のたびに App.tsx の複数箇所（`MAIN_TABS`、ヘルプ文言、レンダリング分岐）を編集する必要がある。URL とタブ状態が同期していないため、リロード・リンク共有で状態が再現できない。

#### D-2. エラー表示が単一 `err` state に集約（重要度: 低）

全パネルが `onError={setErr}` で単一のバナーに書き込む。複数パネル由来のエラーが上書きし合い、原因パネルが分からない。`PanelErrorBoundary` は導入済みなので、非例外系エラーもパネル境界に寄せる余地がある。

#### D-3. ヘルプ文言のハードコード（重要度: 低）

`HELP_CONTENT` が App.tsx 内の文字列リテラルで、`docs/user-guides/` の内容と二重管理になっている。乖離しても検知手段がない。

### E. CI・品質ゲート

#### E-1. Python の型チェックが CI にない（重要度: 中）

CI（`.github/workflows/ci.yml`）は `ruff check` + `pytest` のみで、mypy / pyright が走らない。コードベースは型ヒントが比較的整っている（`Mapped[...]`、`from __future__ import annotations` 等）ため、導入コストに対して回収が大きい状態。

#### E-2. バックエンドのカバレッジ計測が CI にない（重要度: 低）

フロントエンドは `test:coverage` + アーティファクト保存まで整備済みだが、Python 側は `.coverage` がローカルにあるのみで CI では計測・可視化されていない。

#### E-3. E2E が全 push で毎回フル実行（重要度: 低）

`frontend-unit` には paths-filter があるが、`e2e` ジョブにはなく、バックエンドのみの変更でも Playwright + Chromium のセットアップが毎回走る。

---

## 良い点（維持すべき設計）

- ルート → スキーマ → サービス → collectors の層分離が一貫しており、pyVmomi のブロッキング呼び出しを `asyncio.to_thread` に隔離する方針が徹底されている。
- `VCenterRead` から password を除外するなど、API スキーマでの情報露出制御ができている。
- SPA フォールバックのパストラバーサル対策（`is_relative_to` 検証）、`/api` への `Cache-Control: no-store` 付与など、細部の防御が入っている。
- テスト時に `.env` を読まない `VEA_PYTEST` ガードにより、開発者の API キーがテストへ混入しない。
- フロントエンドはパネル・フック・スキーマ（zod 相当の検証層）に分割され、`PanelErrorBoundary` / lazy import も導入済み。

## 重要度サマリ

| ID | 課題 | 重要度 | 主な効果 |
| --- | --- | --- | --- |
| A-1 | スキーマ管理の二重化 | 高 | 変更コスト削減・DB 状態の一意化 |
| B-1 | 資格情報の平文保存 | 高 | 漏洩リスク低減 |
| B-2 | TLS 検証の恒久無効 | 高 | 本番運用の選択肢確保 |
| C-5 | 取り込みの N+1 SELECT | 中〜高 | 障害時の取り込み遅延防止 |
| C-1 | 設定シングルトン依存 | 中 | テスト容易性・将来の動的設定 |
| C-2 | services/ フラット肥大 | 中 | 発見コスト・凝集度 |
| C-4 | スケジューラのガード不足 | 中 | 多重実行・遅延の防止 |
| D-1 | タブ状態の破棄・URL 非同期 | 中 | UX・パネル追加コスト |
| E-1 | 型チェック未導入 | 中 | リグレッション検知 |
| A-2 | 複合インデックス不足 | 中 | 長期保持時の性能 |
| その他 | A-3, B-3, C-3, C-6, D-2, D-3, E-2, E-3 | 低 | — |
