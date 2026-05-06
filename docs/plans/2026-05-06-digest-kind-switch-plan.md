---
name: digest-kind-switch-plan
overview: ダイジェスト一覧で daily/weekly/monthly を切り替え表示できるようにするため、API に kind フィルタを追加し、DigestsPanel から切替クエリを連動させます。後方互換を保ちながら、件数・ページング整合とテスト拡充を行います。
todos:
  - id: setup-worktree
    content: 実装開始前に `using-git-worktrees` に沿って作業用 worktree を作成し、ベースライン確認を行う
    status: pending
  - id: enforce-tdd
    content: 全変更を TDD（Red→Green→Refactor）で進める
    status: pending
  - id: api-kind-filter
    content: "`digests.py` に kind クエリ追加と一覧/件数クエリへの共通フィルタ適用"
    status: pending
  - id: ui-kind-toggle
    content: "`DigestsPanel.tsx` に all/daily/weekly/monthly 切替UIと API クエリ連動を追加"
    status: pending
  - id: tests-backend
    content: "`test_digests_api.py` に kind フィルタと total/page 整合テストを追加"
    status: pending
  - id: tests-frontend
    content: "`DigestsPanel.test.tsx` に切替時のリクエスト・状態リセット検証を追加"
    status: pending
  - id: regression-check
    content: kind 未指定時の既存挙動回帰確認
    status: pending
isProject: false
---

# ダイジェスト種別切替 実装計画

## 目的
`Digests` 画面で `all/daily/weekly/monthly` の切替表示を可能にし、API 側の `kind` フィルタでページング件数と表示内容の整合を維持する。

## 変更方針
- **実装前提（必須）**
  - 実装開始前に `using-git-worktrees` を使用して隔離された worktree を作成する
  - 以後の実装は `test-driven-development` に従い、**必ず Red→Green→Refactor** の順で進める
  - 「失敗するテストを先に追加し、失敗を確認する前に本番コードを書かない」を厳守する

- **API 拡張（後方互換）**
  - [`/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/api/routes/digests.py`](/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/api/routes/digests.py)
  - `GET /api/digests` に任意クエリ `kind` を追加（`daily|weekly|monthly`）
  - 一覧取得クエリと件数クエリの両方へ同一の `kind` 条件を適用
  - `kind` 未指定は現状どおり全件（後方互換）

- **フロント切替 UI 追加**
  - [`/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/digests/DigestsPanel.tsx`](/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/digests/DigestsPanel.tsx)
  - `selectedKind` state（`all|daily|weekly|monthly`）を追加
  - 切替時に `offset=0` へ戻し、`selectedId` をクリアして再取得
  - `apiGet` 呼び出しに `kind` クエリを条件付与
  - 0件時は選択中種別に応じた empty state 文言を表示

- **テスト追加**
  - Backend: [`/Users/moriyama/git/vcenter-event-assistant/tests/test_digests_api.py`](/Users/moriyama/git/vcenter-event-assistant/tests/test_digests_api.py)
    - `kind` 指定時の一覧フィルタ・`total` 整合・ページング整合
  - Frontend: [`/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/digests/DigestsPanel.test.tsx`](/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/digests/DigestsPanel.test.tsx)
    - 種別切替で `kind` 付きリクエスト
    - 切替時の `offset` リセットと選択解除

## 実装ステップ
1. `using-git-worktrees` に従って worktree を作成し、依存関係セットアップとベースライン確認を行う
2. **RED(API)**: `test_digests_api.py` に `kind` フィルタ期待の失敗テストを追加し、失敗を確認する
3. **GREEN(API)**: `digests.py` に最小実装で `kind` クエリフィルタを追加し、APIテストを通す
4. **RED(UI)**: `DigestsPanel.test.tsx` に切替時クエリ/状態リセットの失敗テストを追加し、失敗を確認する
5. **GREEN(UI)**: `DigestsPanel.tsx` に `selectedKind` と切替UIを最小実装し、フロントテストを通す
6. **REFACTOR**: 重複や可読性を整えつつ、追加テストを含めてグリーン維持を確認する
7. `kind` 未指定時の後方互換動作と回帰を確認する

## 影響範囲
- API: `/api/digests` のクエリ仕様が拡張される（既存利用は変更不要）
- UI: Digests一覧の操作系に種別トグルを追加
- DB スキーマ変更なし、`DigestRead` 型変更なし
