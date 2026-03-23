# README ユースケース・特長・不得意 追記 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [README.md](../../../README.md) の冒頭に「主なユースケース」「特長」「不得意・制約」を追加し、初見の読者がプロダクトの位置づけを把握できるようにする。LLM によるダイジェスト補助は **ベータ版**である旨を必ず注記する。

**Architecture:** ドキュメントのみの変更。既存の「商標および免責」「セキュリティ」と矛盾しない文言にし、重複は「詳細は ○○ 節」と参照で短くする。挿入位置は **推奨どおり**、1 行目の説明の直後（[README.md](../../../README.md) 現状の L3 の後）、`## 商標および免責` の前。

**Tech Stack:** Markdown。参照ドキュメント: [docs/plans/2026-03-21-vcenter-event-assistant-as-built.md](../../plans/2026-03-21-vcenter-event-assistant-as-built.md)。ブレインストーミングで確定した内容（アプローチA・LLM ベータ注記）は Cursor 側の計画メモ `readme_ユースケース追記_086fc811.plan.md` と整合させる（リポジトリ外の場合あり）。

---

## ファイル構成

| ファイル | 役割 |
|----------|------|
| [README.md](../../../README.md) | 唯一の変更対象。L3 の後に 3 見出し＋箇条書きを挿入し、必要なら L3 の短文を拡張 |

**変更しないもの:** `pyproject.toml`、`.env.example`、ソースコード、テスト（本タスクはドキュメントのみ）。

**整合性メモ（実装時に必ず守る）:**

- 現行 README の「セキュリティ」は「アプリ自体は認証を行いません」。**アプリ側のオプション認証（Bearer 等）は記載しない**（現リポジトリの [.env.example](../../../.env.example) にも認証変数はない）。
- 特長・不得意でセキュリティと重なる内容は **1 行要約 + [セキュリティ](#セキュリティ) への誘導**。

---

## 差し込み本文ドラフト（実装時に文言調整してよい）

```markdown
## 主なユースケース

- vCenter の **イベント**を蓄積し、時系列で一覧・フィルタし、ルールに基づく **注目度（スコア）** で優先度付けして確認する。
- ESXi ホストの **CPU/メモリ利用率**（`quickStats` 由来）を定期サンプルし、**推移・ダッシュボード**で傾向を見る。
- **複数 vCenter** を登録し、手動またはスケジュールされた **収集ジョブ**でデータを取り込む。
- （任意）期間を指定して **Markdown ダイジェスト**を生成する。環境設定により **LLM で要約・整形**できる（運用レポートの下書き用途）。**LLM によるダイジェスト補助はベータ版**であり、挙動・出力品質・設定は予告なく変わり得ます。

## 特長

- **オープンソース**（[Apache License 2.0](LICENSE)）、**自前ホスト**可能。
- DB は **PostgreSQL / SQLite** を `DATABASE_URL` で選択（[前提](#前提)）。
- 収集は **pyVmomi** 経由。バックエンドは **FastAPI**、フロントは **React** のダッシュボード UI。
- 収集間隔・データ保持日数・ダイジェストのスケジュール等を **環境変数で調整**可能（[.env.example](.env.example) および `Settings`）。

## 不得意・制約

- **本アプリ単体では認証を行いません。本番ではリバースプロキシ等で TLS・認証・ネットワーク制限を行ってください**（詳細は [セキュリティ](#セキュリティ)）。
- **Broadcom / VMware の公式製品ではありません**（[商標および免責](#商標および免責)）。
- ホスト指標は **`quickStats` ベースの限定的な項目**であり、vCenter の全パフォーマンスカウンタ網羅や VM 単位の詳細キャパシティプランニング専用ツールではありません。
- **フル SIEM やコンプライアンス監査の唯一の証跡ソース**としての置き換えは想定しません（保持・改ざん耐性・長期アーカイブは運用設計が別途必要です）。
- **LLM 利用時（ベータ）**は外部 API への送信・コスト・レイテンシ・プロンプトに載るデータ範囲に注意してください。ベータ機能のため、本番の唯一の根拠資料にしない運用を推奨します。
```

**冒頭 1〜2 文の拡張例（L3 を置き換えまたは続ける）:**

```markdown
vCenter のイベントとホスト指標（CPU/メモリ利用率など）を収集し、Web ダッシュボードで一覧・傾向を確認するツールです。期間を指定した **Markdown ダイジェスト**の生成や、環境設定に応じた **LLM による補助（ベータ）**にも対応します。
```

（LLM はベータなので「補助（ベータ）」と括るか、次のセクションで必ずベータと明記する。）

---

### Task 1: 挿入位置と冒頭文の確定

**Files:**

- Modify: [README.md](../../../README.md)（L1–L5 付近）

- [ ] **Step 1:** `## 商標および免責` の **直前**に、上記「差し込み本文ドラフト」ブロック全体を挿入する（見出しレベルは `##` のまま）。

- [ ] **Step 2:** L3 の 1 文を、ダイジェスト（と LLM ベータ）を含めて実装と矛盾しないようにする。上記「冒頭拡張例」をそのまま使うか、1 文に収めるならダイジェスト名のみ入れ、LLM ベータは「主なユースケース」の箇条書きで必ず触れる。

- [ ] **Step 3:** 目視でアンカーリンク（`[セキュリティ](#セキュリティ)` 等）が GitHub 上で機能する見出し文言と一致するか確認する（見出しは既存のままなら一致）。

---

### Task 2: 内容の整合レビュー（コード・README との突合）

**Files:**

- Read-only: [README.md](../../../README.md)（全体）
- Read-only: [docs/plans/2026-03-21-vcenter-event-assistant-as-built.md](../../plans/2026-03-21-vcenter-event-assistant-as-built.md)（任意・用語確認）

- [ ] **Step 1:** 「LLM ダイジェストはベータ」が **少なくとも 1 箇所**（ユースケースまたは不得意）で明確か確認。

- [ ] **Step 2:** 「認証」について README の「セキュリティ」節と **矛盾がない**か確認（特長にアプリ認証を追加しない）。

- [ ] **Step 3:** `quickStats`、イベントのスコア、ダイジェスト API の存在を誇張していないか確認（必要なら as-built の用語に合わせる）。

---

### Task 3: 検証（自動テストは不要、任意コマンド）

本変更は Markdown のみ。CI は README 変更で通常は追加不要。

- [ ] **Step 1（任意）:** `uv run ruff check src tests` — 変更なしでも通ることを確認（リグレッション用）。

- [ ] **Step 2（任意）:** `uv run pytest -q` — 同上。

期待: 変更がない場合は既存どおり PASS。

---

### Task 4: コミット

- [ ] **Step 1:** 差分確認

```bash
git diff README.md
```

- [ ] **Step 2:** コミット（Conventional Commits）

```bash
git add README.md
git commit -m "docs: add use cases, strengths, and limitations to README"
```

本文に、ベータ注記とセキュリティ節との整合を 1〜2 文で書くとよい。

---

## Plan review ループ（任意）

- レビュー対象: 本ファイル
- 参照: ブレインストーミングで合意した README 方針（アプローチA、LLM ダイジェストのベータ注記）

`plan-document-reviewer` サブエージェントが利用可能なら 1 回レビューを依頼し、指摘があれば本計画を修正してから実装へ。

---

## 実行時の選択肢

**Plan complete and saved to `docs/superpowers/plans/2026-03-23-readme-use-cases-positioning.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — タスクごとに新しいサブエージェントを起動し、タスク間でレビューする
2. **Inline Execution** — このセッションで `executing-plans` に沿ってチェックボックスを順に実行する

**Which approach?**
