# プラン用 Git / ブランチ方針（スニペット）

実装計画（`docs/superpowers/plans/*.md` および `docs/plans/*.md`）に貼り付けるか、本ファイルへのリンクを置く。

## Git / ブランチ方針

- **`main` 上での直接実装・直接コミットは行わない**（ユーザーが **`main` でよい**と明示した場合のみ例外）。
- 作業は **feature ブランチ**、または **`git worktree` による隔離ワークツリー**上で行う。
- **コード変更・コミットに入る前**に、読み取り専用のシェルで少なくとも次を実行し、作業報告の冒頭で短文共有する。
  - `git branch --show-current`（空なら detached の可能性）
  - `git rev-parse --show-toplevel`
  - 可能なら `pwd`（`.worktrees/...` かリポジトリ直下かの目安）
- **実装開始（プラン Task 1 のコード編集前）**は Superpowers の **`using-git-worktrees`** に従い隔離ワークツリーを用意する。
  - 本リポジトリではプロジェクト直下の **`.worktrees/`** を優先する（なければ `worktrees/`）。プロジェクトローカル配置の場合は、作成前に **`git check-ignore`** で誤追跡を防ぐ。
  - プラン本文には推奨ブランチ名（例: `feature/<topic>`）と期待パス（例: `.worktrees/feature-<topic>/`）を1行書いてよい。
- **`main` へのマージ・`git push origin main`** はユーザーの明示がない限りエージェントから実行しない。
- **`git push` / PR 作成前**（`tests/` を変更した場合は必須）: `uv run ruff check tests/`。広い変更や CI と完全に揃えるときは `uv run ruff check src tests`（[development.md](../development.md) の「PR 前のローカルチェック」）。

詳細と例外は [git-branch-worktree-before-changes の Cursor ルール](../../../.cursor/rules/git-branch-worktree-before-changes.mdc) に合わせる。
