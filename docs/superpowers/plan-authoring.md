# 実装計画の書き方（本リポジトリ）

Superpowers の **`writing-plans`** で計画を書くとき、プラグイン既定のヘッダに加え、本リポジトリでは **Git / ブランチ方針**を必ず盛り込む。

## `writing-plans` との関係

- 保存先の既定は `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`（ユーザー指定があればそれに従う）。
- プラグインが要求する **Plan Document Header**（Goal / Architecture / Tech Stack / `---`）はそのまま使う。
- **ヘッダ直下の `---` の直後**に、次のブロックを置く（順序は固定とする）。
  1. **`## Git / ブランチ方針`** 見出し
  2. [`docs/process/snippets/git-branch-policy-for-plans.md`](../process/snippets/git-branch-policy-for-plans.md) の内容を **そのままコピー**するか、**要約1段落＋同ファイルへのリンク**のみとする。

この節は **「記載内容すべてを実装で満たした」ことの保証ではなく**、プラン作成時に **手続として読み・プランへ載せた**ことの宣言である。実装フェーズでは Cursor の Superpowers スキル **`using-git-worktrees`** を実装ゲートとして用いる。

## `using-git-worktrees`（実装前ゲート）

- **プラン Task 1 でコード編集・コミットに入る前**に、`using-git-worktrees` に従い隔離ワークツリーを用意する。
- プラン本文では推奨ブランチ名（例: `feature/<topic>`）と、期待するワークツリーパス（例: `.worktrees/feature-<topic>/`）を **1行で記載**してよい。
- 本リポジトリでは `.worktrees/` を優先し、プロジェクトローカル配置では **`git check-ignore`** で誤追跡を防ぐ（スキル手順どおり）。

## `writing-plans` の Execution Handoff との整合

プラグイン末尾の「実行オプション」文言と矛盾させないため、本リポジトリの **Git / ブランチ方針**では「**コード編集・コミットに入る前**」にワークツリーを用意すると明記する（プラン承認後・実行ハンドオフ前でもよいが、**最初の編集より前**が必須）。

## 参照

- スニペット本体: [`docs/process/snippets/git-branch-policy-for-plans.md`](../process/snippets/git-branch-policy-for-plans.md)
- 編集セッション全般: `.cursor/rules/git-branch-worktree-before-changes.mdc`
- プラン準拠運用: [`docs/process/plan-compliance-operating-guide.md`](../process/plan-compliance-operating-guide.md)
