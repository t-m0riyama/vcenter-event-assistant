# アーキテクチャ改善プラン実装レビュー（2026-07-05）

[architecture-improvement-plan-2026-07-05.md](architecture-improvement-plan-2026-07-05.md)（Grilling 決定事項含む）に基づく実装（コミット範囲 `72f9fbb..8741c34`、144 ファイル / 約 3,500 行）の再レビュー結果。

## 結論

**プランと Grilling 決定事項はすべて忠実に実装されており、ブロッカーなし。**

- mypy: issue なし
- バックエンドテスト: 326 件全 pass
- フロントエンドテスト: 457 件全 pass（71 ファイル）

未実施は 2-3（取り込みカーソルの型改善、プラン上「任意」）のみ。3-3（API トークン）は保留の決定どおり未実装。

## 各項目の適合確認

| 項目 | 判定 | 確認内容 |
| --- | --- | --- |
| 1-1 mypy | ✅ | `ci.yml` python ジョブ内で必須実行 |
| 1-2 カバレッジ | ✅ | アーティファクト保存のみ、fail-under なし（決定どおり） |
| 1-3 E2E paths-filter | ✅ | `src/**`・`tests/**` を含む。`on.push.branches: [main, master]` のため「push = main への push」となり、`github.event_name == 'push'` 条件で常時実行の決定を満たす |
| 1-4 N+1 解消 | ✅ | dialect 別 `on_conflict_do_nothing` + `rowcount`。`index_elements` に対応する一意制約（`uq_event_vcenter_vmware_key` / `uq_metric_sample_point`）は初期スキーマから存在するため PostgreSQL でも安全。1,000 件バースト + SELECT 非発行テスト（`tests/test_ingestion.py`）が CI で毎回実行される |
| 2-1 Alembic 一本化 | ✅ | `init_db` は stamp/upgrade 分岐、曖昧 fingerprint は `LegacySchemaStampError` で起動 abort（決定どおり）。リビジョンチェーンは一本道で単一 head（`c4d27748ae50` → … → `p2q3r4s5t6u7`） |
| 2-2 複合 index | ✅ | リビジョン `n1o2p3q4r5s6` + モデル定義 + `test_composite_indexes.py` |
| 2-3 カーソル型改善 | ―（任意） | 未実施。プラン上「任意」のため問題なし |
| 3-1 パスワード暗号化 | ✅ | `EncryptedString` TypeDecorator、`enc:` プレフィックス、鍵未設定時 WARNING + 平文継続（fail-closed 不採用の決定どおり）、起動時一括移行、ローテーション失敗時の明確なエラー。docker-compose / .env.example への記載も確認 |
| 3-2 TLS 検証 opt-in | ✅ | `verify_ssl` 列 → collectors まで伝搬、`VCENTER_CA_BUNDLE` 対応、接続テスト成功時に「本番では SSL 証明書検証を推奨」を UI 表示（決定どおり） |
| 3-3 API トークン | ✅ | 未実装（保留の決定どおり） |
| 4-1 services 分割 | ✅ | `chat/` `digest/` `llm/` `alerting/` サブパッケージ化、tests もミラー、re-export なし |
| 4-2 設定 DI | ✅ | `get_settings()` 直呼びは `main.py` と `api/deps.py` のみ（scheduler も呼ばない） |
| 4-3 スケジューラ整理 | ✅ | ジョブのモジュールレベル関数化、全ジョブに `coalesce=True, max_instances=1`、`purge_interval_hours` 設定化、`asyncio.gather` + `Semaphore(ingestion_concurrency)`（既定 3）、per-vCenter 失敗分離維持 |
| 4-4 AlertEvaluator | ✅ | `_RULE_EVALUATORS` 辞書ディスパッチ、依存明示化 |
| 4-5 レガシーダイジェスト | ✅ | `legacy_settings_deprecation.py` で起動時 WARNING、削除は 2 リリース後と明記 |
| 5-1 タブ URL 同期 | ✅ | ハッシュ同期 + 遅延マウント→維持（`hidden` 属性）。初回表示までフェッチしない実装で、常時マウントの無駄フェッチを回避 |
| 5-2 エラー局所化 | ✅ | パネル内エラー領域へ移行 |
| 5-3 ヘルプ一元化 | ✅ | `tabHelpContent.ts` に `userGuideDoc` を持たせ、参照先ドキュメントの実在をテストで検証（乖離検知の要件を満たす） |

## 指摘事項（いずれも軽微、ブロッカーなし）

### 1. `ALEMBIC_HEAD` の二重管理（優先度: 中）

`src/vcenter_event_assistant/db/alembic_runner.py:15` の定数は src 内で未使用のデッドコードで、同じ値が `tests/test_db_session_migrations.py:17` に重複している。リビジョン追加のたびに手動更新が必要で忘れやすい。

- 対応案: src 側の定数を削除。テスト側はトリップワイヤとして残すか、`alembic.script.ScriptDirectory` から head を導出して保守を不要にする。

### 2. `enc:` で始まる平文パスワードの縁ケース（優先度: 低）

`encrypted_string.py` の `process_bind_param` は `enc:` 始まりの値を「暗号化済み」とみなすため、実パスワードがたまたま `enc:` で始まると平文保存され、読み出し時に復号失敗する。実運用でほぼ起きないが、API 側で `enc:` 始まりを拒否するか docstring に制約を明記すると堅くなる。

### 3. 鍵導出が無ソルト SHA-256（優先度: 低）

`fernet_key_bytes` は SHA-256 のみで鍵を導出しており、弱いパスフレーズに対して総当たり耐性がない。ランダム鍵なら問題ないため、`.env.example` に `openssl rand -base64 32` 等での生成例を追記するとよい。

### 4. 細かい点（優先度: 低）

- `jobs/scheduler.py` の `_one(vid: int)` — vCenter ID は UUID のため型注釈が誤り。
- パージジョブ ID `"purge_metrics"` — イベントも削除するため名前が実態とずれている。
- 取り込みは SELECT こそ消えたが INSERT は 1 行ずつのまま。受け入れ条件は満たしているが、さらに詰めるなら executemany 化の余地がある。

### 5. `settings_binding` はサービスロケータの再導入（判断: 許容）

`settings_binding.py` のプロセスグローバル bind は 4-2 の DI 方針と逆行するが、`TypeDecorator` に注入経路がない以上妥当な妥協。`require_settings` の利用箇所も session / 暗号化層に限定されており、意図的なトレードオフとして問題なし。

## 総評

単なるプラン消化ではなく、Grilling 決定事項（曖昧 stamp の abort、遅延マウント、main push での CI 常時 E2E、fail-under なしのカバレッジ等）まできちんと反映された質の高い実装。指摘 1（`ALEMBIC_HEAD`）のみ次のリビジョン追加時に忘れやすいため、早めの対応を推奨する。

---

## Grilling 決定事項 — 指摘対応（2026-07-05）

再レビュー後の `/grill-me` セッションで確定した指摘対応方針。

| 論点 | 決定 |
| --- | --- |
| **#1 `ALEMBIC_HEAD` 二重管理** | `get_alembic_head()` を `ScriptDirectory` から動的導出。定数は削除 |
| **#2 `enc:` 始まりパスワード** | API 層（`VCenterCreate` / `VCenterUpdate`）で拒否 + テスト |
| **#3 鍵導出（SHA-256）** | `.env.example` / docker-compose に `openssl rand -base64 32` 生成例を追記（PBKDF2 は見送り） |
| **#4 INSERT bulk 化** | GitHub Issue #123 に起票して保留（N+1 SELECT 解消済み） |
| **#5 細かい修正** | `_one(vid: uuid.UUID)` 型注釈を同 PR に同梱。`purge_metrics` ジョブ ID リネームは今回対象外 |
| **#5 `settings_binding`** | 対応不要（意図的トレードオフとして許容） |
| **PR 分割** | 上記を 1 PR（`chore: post-architecture-review fixes`）にまとめる |
