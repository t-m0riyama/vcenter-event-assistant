# README.md の整理とドキュメント分割 実施計画

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** `README.md` の内容を整理し、セットアップ方法、起動手順、開発用コマンドなどの詳細情報を `docs/` 配下の別ファイルに分割して軽量化する。

**Architecture:** `README.md` はプロジェクトの概要と制約事項に絞り、利用開始手順を `docs/getting-started.md` へ、開発者向け詳細を `docs/development.md` へ移動・整理する。

**Tech Stack:** Markdown

---

### Task 1: `docs/getting-started.md` の作成

**Files:**
- Create: `docs/getting-started.md`

**Step 1: `README.md` からコンテンツを抽出して新規ファイルを作成**

`README.md` の「前提」「セットアップ」「起動」「セキュリティ」セクション（旧 README 65行目〜174行目付近）を移動します。

**Step 2: 作成したファイルの確認**

Run: `ls -l docs/getting-started.md`
Expected: ファイルが存在すること。

**Step 3: Commit**

```bash
git add docs/getting-started.md
git commit -m "docs: create getting-started.md from README contents"
```

---

### Task 2: `docs/development.md` の更新

**Files:**
- Modify: `docs/development.md`

**Step 1: `README.md` から「データベースマイグレーション」と「開発」の内容を `docs/development.md` の先頭に統合**

`docs/development.md` の 2 行目（最初の空行）以降に、README から抽出した内容を挿入します。

**Step 2: Commit**

```bash
git add docs/development.md
git commit -m "docs: move migration and development commands to development.md"
```

---

### Task 3: `README.md` のリファクタリング

**Files:**
- Modify: `README.md`

**Step 1: 移動済みセクションの削除とリンクの更新**

`README.md` から以下のセクションを削除します：
- ## 前提
- ## セットアップ
- ## 起動
- ## セキュリティ
- ## データベースマイグレーション
- ## 開発

そして、`## ドキュメント` セクションに `docs/getting-started.md` へのリンクを追加し、構成を整えます。

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: slim down README.md and update document links"
```

---

## 完了の検証
1. `README.md` が軽量化され、指定されたセクションのみが残っていることの確認。
2. `docs/getting-started.md` が正しく構成されていることの確認。
3. `docs/development.md` に開発用コマンド等が正しく追加されていることの確認。
