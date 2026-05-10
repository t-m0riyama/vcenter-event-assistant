# スナップショット `graph_context` とグラフ再生（TDD 実装プラン）

> **エージェント向け:** 各フェーズは **テストを先に追加（RED）→ 実装（GREEN）→ 必要ならリファクタ** の順で進める。フェーズ完了ごとに該当テストコマンドを実行し、証跡を残す。

**ゴール:** 手動スナップショットにオプションの `graph_context`（メトリクス再生用メタデータ）を保存・取得でき、保存済みスナップショットから **メトリクスタブへ遷移してグラフを再生**できる。タイムライン上にはスナップショットマーカーを重ね表示する。スコープ・非目標は Cursor 側の設計プラン `snapshot_graph_metadata_6fd4390b.plan.md` と整合させる。

**技術スタック:** Python（pytest / httpx）+ Alembic、TypeScript（Vitest / Testing Library）、React、既存 FastAPI ルート。

---

## Git / ブランチ方針

本プランは [docs/superpowers/plan-authoring.md](../superpowers/plan-authoring.md) に従い、実装計画に **Git / ブランチ方針**を含める。

- **`main` 上での直接実装・直接コミットは行わない**（ユーザーが `main` でよいと明示した場合のみ例外）。
- 作業は **feature ブランチ**、または **`git worktree` による隔離ワークツリー**上で行う。
- **コード変更・コミットに入る前**（本プランでは **フェーズ 0 のプロダクションコードに触れる前／または Task 1 相当の編集前**）に、読み取り専用のシェルで少なくとも `git branch --show-current`、`git rev-parse --show-toplevel`、可能なら `pwd` を実行し、作業報告の冒頭で短文共有する。
- **実装開始（最初の本番コード編集前）**は Superpowers の **`using-git-worktrees`** に従い隔離ワークツリーを用意する。本リポジトリではプロジェクト直下の **`.worktrees/`** を優先する（なければ `worktrees/`）。ローカル配置の場合は作成前に **`git check-ignore`** で誤追跡を防ぐ。
- 推奨例: ブランチ `feature/snapshot-graph-context`、ワークツリー `.worktrees/feature-snapshot-graph-context/`（実装時に確定してよい）。
- **`main` へのマージ・`git push origin main`** はユーザーの明示がない限りエージェントから実行しない。

**スニペット全文または要約の正本:** [docs/snippets/git-branch-policy-for-plans.md](../snippets/git-branch-policy-for-plans.md)。詳細と例外は `.cursor/rules/git-branch-worktree-before-changes.mdc` に合わせる。

---

## TDD の適用ルール（共通）

1. **同一コミット単位では、プロダクション変更に先立って失敗テストが存在すること**（既存挙動を変えないリファクタのみ例外可）。
2. **RED:** 追加・変更したテストが失敗することをローカルで確認してから実装に入る。
3. **GREEN:** 最小の実装でテストを通す。
4. **Refactor:** 重複排除・命名はテストが緑のまま行う。
5. **検証コマンド（フェーズ末）**
   - バックエンド: `uv run pytest tests/test_incident_timeline_api.py`（拡大時は関連パスのみから段階的に全体へ）
   - フロントエンド: `npm run --prefix frontend test -- <対象パス>`

---

## Subagent-Driven Development での実行（Superpowers）

本プランを **同一セッション内でサブエージェントに任せて進める**場合は、Superpowers の **`subagent-driven-development`** に従う。要点のみここに写す（詳細はプラグインの `subagent-driven-development` スキル本体）。

### 事前（親エージェント／オーケストレータ）

1. **`using-git-worktrees` を完了してから**最初の実装サブエージェントを起動する（上記 Git 方針と [plan-authoring.md](../superpowers/plan-authoring.md) の「Task 1 のコード編集前」に相当）。
2. 本ファイルを **一度読み**、下記 **タスク一覧の該当行を全文コピー**してサブエージェントに渡す（サブエージェントにプランファイルを読ませるだけに依存しない）。
3. `TodoWrite` 等でタスクを列挙し、**常に 1 タスクずつ**実装サブエージェントを起動する（並列の実装サブエージェントは禁止。競合する）。

### タスクあたりのゲート（順序固定）

各タスクで次の順を守る。**コード品質レビューを仕様適合レビューより先にしない。**

| 順序 | 役割 | 合格条件の目安 |
|------|------|----------------|
| 1 | **実装サブエージェント** | 本プランの当該フェーズの TDD（RED→GREEN）、テスト実行、必要ならコミット、自己レビュー。`DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED` は親が内容を確認してから再投入。 |
| 2 | **仕様適合レビュー** | 本プランおよび上位設計（`graph_context` 非目標・API 契約など）に対し過不足なし。 |
| 3 | **コード品質レビュー** | 可読性・重複・境界条件・セキュリティ上の明らかな問題なし。 |

いずれかで差し戻しがあれば **同じタスクの実装サブエージェントに修正→該当レビューを再実行**し、両方 ✅ になるまで次タスクに進まない。

### タスク分割（本プランとの対応）

| ID | 内容 | 主な成果物 |
|----|------|------------|
| SDD-0 | フェーズ 0 全文 | `GraphContext` モデル + 単体テスト |
| SDD-1 | フェーズ 1 全文 | Alembic + ORM + 永続化テスト |
| SDD-2 | フェーズ 2 全文 | 手動スナップショット API + `test_incident_timeline_api.py` |
| SDD-3 | フェーズ 3 全文 | zod + `TimelinePanel` 保存ペイロード + テスト |
| SDD-4 | フェーズ 4 全文 | メトリクス遷移・再生・縦線（大きい場合は親が 4a/4b に分割してよい） |
| SDD-5 | フェーズ 5 全文 | タイムライン上マーカー + テスト |
| SDD-6 | フェーズ 6 全文 | 設計書・全テスト・手動確認 |

### 終了時

- 全タスク完了後、**最終コードレビュー**（必要ならサブエージェント）を実施する。
- ブランチ統合方針は **`finishing-a-development-branch`** に従う（`main` 直マージ禁止は前述どおり）。

### サブエージェント向け TDD

実装サブエージェントは **`test-driven-development`** スキルに従い、本プランの「フェーズ内 Step」を満たすこと。

---

## フェーズ 0: 契約の固定（テストのみ可）

**目的:** `GraphContext` の JSON 形を Pydantic / Zod で単体テストし、API に載せる前に振る舞いを固定する。

| Step | 作業 | 検証 |
|------|------|------|
| 0-1 | `GraphContext` 用の Pydantic モデル（新規モジュールまたは `api/schemas/chat.py` 内）を**まだ本番ルートは触らず**、`tests/` に **バリデーション成功・失敗（未知キー拒否・文字数上限など）** の単体テストを追加 | RED（モデル未実装なら import 失敗） |
| 0-2 | モデル実装 | GREEN |

**成果物:** `GraphContext` の単体テスト + モデル。

---

## フェーズ 1: DB と ORM（マイグレーション後の永続化テスト）

| Step | 作業 | 検証 |
|------|------|------|
| 1-1 | Alembic リビジョン追加（`graph_context` JSON nullable）。**マイグレーション適用前**に、ORM で `graph_context` を読み書きする **統合テストをスキップ or xfail 付きで追加** するか、まず **マイグレーション存在のスモーク**（オプション） | 方針に合わせて RED を定義 |
| 1-2 | マイグレーション適用、`IncidentTimelineManualSnapshot` にカラムマッピング | 統合テスト GREEN |

**成果物:** マイグレーション + モデル更新 +（推奨）セッション経由の round-trip テスト。

---

## フェーズ 2: API（手動スナップショット POST / GET）

**ファイル想定:** [src/vcenter_event_assistant/api/routes/incident_timeline.py](../../src/vcenter_event_assistant/api/routes/incident_timeline.py)、[src/vcenter_event_assistant/api/schemas/chat.py](../../src/vcenter_event_assistant/api/schemas/chat.py)

| Step | 作業 | 検証 |
|------|------|------|
| 2-1 | `tests/test_incident_timeline_api.py` に **`graph_context` を含む POST `/api/incident-timeline/snapshots/manual`** が 201 で返り、GET 一覧で同一 JSON が得られるテストを追加 | RED |
| 2-2 | リクエスト / レスポンススキーマ・ルート・モデル保存を実装 | GREEN |
| 2-3 | **異常系:** 型不正・サイズ超過で 422 になるテストを追加（RED→GREEN） | GREEN |
| 2-4 | **後方互換:** `graph_context` 省略時は従来どおり動作するテスト | GREEN |

**成果物:** API 契約と回帰カバレッジ。

---

## フェーズ 3: フロント Zod と保存ペイロード

**ファイル想定:** [frontend/src/api/schemas.ts](../../frontend/src/api/schemas.ts)、[frontend/src/api/schemas.test.ts](../../frontend/src/api/schemas.test.ts)、[frontend/src/panels/timeline/TimelinePanel.tsx](../../frontend/src/panels/timeline/TimelinePanel.tsx)

| Step | 作業 | 検証 |
|------|------|------|
| 3-1 | `schemas.test.ts` に `graph_context` 付きレスポンスの parse テスト追加 | RED |
| 3-2 | zod スキーマ拡張 | GREEN |
| 3-3 | `TimelinePanel.test.tsx` で **保存 POST ボディに `graph_context` が含まれる**（メトリクスタブ未実装なら null または最小オブジェクト）ことを先に期待 | RED→GREEN |

---

## フェーズ 4: メトリクスタブへの遷移と再生（結合寄り）

**ファイル想定:** [frontend/src/App.tsx](../../frontend/src/App.tsx)、[frontend/src/panels/metrics/MetricsPanel.tsx](../../frontend/src/panels/metrics/MetricsPanel.tsx)、[frontend/src/hooks/useMetricsPanelController.ts](../../frontend/src/hooks/useMetricsPanelController.ts)

| Step | 作業 | 検証 |
|------|------|------|
| 4-1 | `App.main-tabs.test.tsx` または専用テストで、「スナップショットからグラフで開く」操作後 **`tab === 'metrics'`** かつ **メトリクス取得 API が期待パラメータ**（`metric_key`、期間、vcenter）で呼ばれることをモック検証 | RED |
| 4-2 | `onNavigateToMetricsWithSnapshot`（仮称）と state 伝播を実装 | GREEN |
| 4-3 | **縦線:** `MetricsPanel` のチャートに `ReferenceLine` 等を足す場合、**データ変換関数の単体テスト**を先に追加（ms 変換・ドメイン外スナップショットは描画しない等） | TDD 小刻み |

---

## フェーズ 5: タイムライン上のスナップショットマーカー

**ファイル想定:** [frontend/src/panels/chat/IncidentTimelinePanel.tsx](../../frontend/src/panels/chat/IncidentTimelinePanel.tsx)、[TimelinePanel.tsx](../../frontend/src/panels/timeline/TimelinePanel.tsx)

| Step | 作業 | 検証 |
|------|------|------|
| 5-1 | `IncidentTimelinePanel.test.tsx` に「`snapshotMarkers` prop があるとラベル／マーカーが DOM に出る」テスト | RED→GREEN |
| 5-2 | `TimelinePanel` が GET 済みスナップショットから markers を組み立てて渡す | GREEN |

---

## フェーズ 6: 仕上げ

- [ ] 設計書 [docs/superpowers/specs/](../superpowers/specs/) に `graph_context` フィールド一覧・非目標を追記（未作成なら新規）。
- [ ] `uv run pytest` と `npm run --prefix frontend test` を可能な範囲で全通し。
- [ ] 手動確認: スナップショット保存 → 一覧 → グラフで開く → 折れ線と縦線。

---

## リスクとテスト観点

- **保持期間外メトリクス:** 再生時に API が空でも落ちず、ユーザーにヒントを出す（UI テストまたは単純な分岐テスト）。
- **`graph_context` 欠損:** タイムラインのみ保存の場合は「グラフで開く」を無効化または部分適用（テストで固定）。

---

## 参照

- 上位のスコープ・非目標: Cursor プラン `snapshot_graph_metadata_6fd4390b.plan.md`（ローカル `.cursor/plans/`、またはチーム共有の同等ドキュメント）。
