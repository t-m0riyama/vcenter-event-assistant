# プラン準拠運用ガイド（最小運用）

## 目的
最小コストで「プランと異なる実装」を防ぎ、要件・テスト・合意履歴を追跡可能にする。

## 対象
- `docs/plans/*.md` に基づく実装作業
- 新規機能、既存機能改善、バグ修正

## 使用ドキュメント
- `docs/process/plan-compliance-checklist.md`
- `docs/process/plan-to-test-mapping-template.md`
- `docs/process/pr-plan-compliance-section-template.md`
- `docs/process/plan-change-request-template.md`
- `docs/process/examples/incident-timeline-plan-compliance-example.md`

## 導入ステップ
1. 着手時に `plan-compliance-checklist.md` をコピーして案件用チェックシートを作成する。
2. プラン要件へ `REQ-xx` を付与し、`plan-to-test-mapping-template.md` に転記する。
3. 要件ごとにREDテストを先に追加し、実装は要件単位で進める。
4. 逸脱が必要になったら実装を止め、`plan-change-request-template.md` で合意を取る。
5. PR作成時に `pr-plan-compliance-section-template.md` を本文へ貼り付ける。

## 運用ルール
- 合意前の仕様変更実装を禁止する。
- 要件に紐づかない変更はPRに含めない。
- `未対応` と記載した要件は次アクションを必須記載にする。
- 要件完了判定前に、高速エラー検知ゲートを必須実施する（総合テストの代替ではなく早期検知用）。
- Python コマンド実行と Python テスト実行は `uv run` を必須とする（`python` / `pytest` の直接実行を禁止）。
- 実行コンテキストは `working_directory` に依存しない。コマンド引数で worktree 絶対パスを明示する。
  - 例: `git -C "<worktree-abs-path>" ...`
  - 例: `npm --prefix "<worktree-abs-path>/frontend" ...`
  - 例: `uv run pytest "<worktree-abs-path>/tests/..." ...`

## 高速エラー検知ゲート（恒久ルール）
各要件の完了判定前に、少なくとも次を同じ作業コンテキスト（同一 branch / toplevel / pwd）で実施する。

1. 作業コンテキスト確認  
   - `git branch --show-current`  
   - `git rev-parse --show-toplevel`  
   - `pwd`
   - 必要に応じて `git -C "<worktree-abs-path>" branch --show-current` で対象 worktree を再確認
2. Python要件では import 実体確認（`uv run` 必須）  
   - `uv run python -c "import vcenter_event_assistant; print(vcenter_event_assistant.__file__)"`
3. 静的/構文レベルの早期検知  
   - Python: `uv run pytest --collect-only <task関連テスト>` または同等の import 検証  
4. 要件個別テスト + 関連統合テストの最小セット実行  
   - どちらか片方のみ成功は「部分成功」とみなし、次タスクへ進まない。

## 部分成功の禁止（恒久ルール）
- 要件内のテストが「一部成功・一部失敗」の状態を許容しない。
- 部分成功（部分的失敗）が発生した場合、失敗原因を解消するまで次工程に進んではならない。
- 例外運用は、ユーザが明示的に承認した場合に限り許容する。
- 例外運用時は、次を記録する。
  - 承認者（ユーザ）
  - 承認日時
  - 失敗しているテストと影響範囲
  - 次工程での追加検証とロールバック方針

## 役割分担
- 実装者: 要件ID付与、マッピング更新、テスト証跡記録
- レビュアー: Plan Compliance節の妥当性確認、逸脱の合意有無確認
- オーナー: 逸脱申請の承認判断

## 受け入れ条件
- 第三者が以下を追跡できること:
  - どの要件を満たしたか
  - どのテストで検証したか
  - どの仕様変更が合意済みか
- 新規PRで Plan Compliance 節を再利用できること。
- 初回運用者が10分以内に記入を開始できること。

## 改善サイクル（1〜2スプリント後）
- 記入時間、レビュー時間、逸脱検知件数を計測する。
- 記入負荷が高い項目を削減し、未検知が出た項目を強化する。
- 必要なら CI で要件対応テストを必須ジョブ化する。

## 最短開始手順（10分）
1. `plan-compliance-checklist.md` をコピーして案件名で保存する。
2. プランから要件ID（`REQ-xx`）を3〜5件だけ先に採番する。
3. `plan-to-test-mapping-template.md` に要件IDと想定テスト名を記入する。
4. PR作成時に `pr-plan-compliance-section-template.md` を貼る。
5. 逸脱が出た場合だけ `plan-change-request-template.md` を起票する。
