# Project Agent Skills

このディレクトリは、このリポジトリ固有の Agent Skill の Git 追跡上の正本である。
Cursor、Codex、Claude Code、GitHub Copilot（VS Code 拡張）で同じ Skill を利用する。

## 収録している Skill

| Skill | 用途 | 呼び方 |
| --- | --- | --- |
| [capture-ui-screenshots](capture-ui-screenshots/SKILL.md) | ドキュメント用 UI スクリーンショットを Playwright で取得し `docs/images` に保存する。ログイン画面・利用者ガイド・frontend.md の画面例の更新に使う | Claude Code: `/capture-ui-screenshots`<br>他: 「スクリーンショットを最新化して」「docs/images を取り直して」「ログイン画面のキャプチャ」と依頼 |

各自が `.agents/skills/` などへ個人導入した Skill も一覧には出るが、このディレクトリの
管轄外であり正本へ取り込まない。

## 公開先

- Cursor: `.cursor/skills/<name>`
- Codex: `.agents/skills/<name>`
- Claude Code: `.claude/skills/<name>`
- GitHub Copilot（VS Code）: `.agents/skills/<name>` を Codex と共用

## セットアップ

clone または worktree 作成後、AI エージェントのセッションを開始する前に実行する。

```bash
uv run python scripts/link_skills.py
```

macOS では正本への相対 symlink、Windows では Developer Mode を必要としない Directory
Junction を作成する。現在の状態を変更せず検査する場合は次を実行する。

```bash
uv run python scripts/link_skills.py --check
```

正しいエイリアスが既にあれば何も変更しない。既存の実ディレクトリ、通常ファイル、別の場所を
指すエイリアス、解決不能なエイリアスが同名で存在する場合は、内容を保護して処理全体を失敗させる。
Skill を追加した後も bootstrap を再実行し、各製品では新しいセッションで一覧を確認する。

## 管理方針

- プロジェクト Skill は `skills/<name>/SKILL.md` に追加し、実行時公開先を直接編集しない。
- `skills/` 直下で `SKILL.md` を持つディレクトリだけを公開する。
- `name` とディレクトリ名には小文字英数字とハイフンだけを使う。
- 共有する frontmatter と本文は Agent Skills の共通仕様を基本とし、製品固有機能へ無条件に依存しない。
- `.agents/skills/` などに存在する個人導入 Skill は、正本へ取り込まず変更もしない。
- 実行時エイリアスは Git 管理しないため、各社のクラウド実行環境はこの仕組みの対象外とする。
