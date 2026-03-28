# 週次・月次専用ダイジェストテンプレート実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: `**@superpowers:subagent-driven-development**`（推奨）または `**@superpowers:executing-plans**`。ステップはチェックボックス（`- [ ]`）で追跡する。
>
> **TDD（前提）:** `**@superpowers:test-driven-development**` を**必須**とする。実装前に **失敗するテスト** を置き、**最小実装 → グリーン → リファクタ** の順のみ進める（Settings の新フィールドも、**テストがその名前を要求してから**追加する）。コミットは **タスク単位またはグリーンごと**（頻繁に）。

**Goal:** `kind` が `weekly` / `monthly` のとき、**任意で**日次（既定）とは別ファイルの Jinja2 テンプレを読めるようにする。週次・月次専用パスが **未設定（空）** のときは、現行どおり **`DIGEST_TEMPLATE_PATH` → `DIGEST_TEMPLATE_DIR` + `DIGEST_TEMPLATE_FILE` → 同梱 `digest.md.j2`** の解決にフォールバックする（後方互換）。

**Architecture:** [`digest_markdown.py`](../../src/vcenter_event_assistant/services/digest_markdown.py) のテンプレ読込を `kind` 対応にする。既存の単一解決ロジックは **`_load_default_template_source(settings)`** などに抽出し、`render_digest_markdown` から呼ぶ `_load_template_source(settings, kind: str)` は **先に** `kind` とオプションの週次・月次パスを見て分岐する。専用パスが **非空**でファイルが読めない場合は **例外**（既存の `digest_template_path` と同様。**DIR や同梱にはフォールバックしない**）。[`digest_run.py`](../../src/vcenter_event_assistant/services/digest_run.py)・API・DB は変更不要。

**Tech Stack:** Python 3.12+、Pydantic Settings、Jinja2、pytest、既存 [`tests/test_digest_markdown.py`](../../tests/test_digest_markdown.py) パターン。

**関連ドキュメント:** 既存テンプレ解決の spec は [`docs/superpowers/specs/2026-03-23-digest-markdown-template-design.md`](../specs/2026-03-23-digest-markdown-template-design.md)。本変更は **種別ごとのオプション PATH** を追加する拡張である。

**スコープ外:** フロントエンド、OpenAPI スキーマ変更、`kind` の新値。`DIGEST_TEMPLATE_DIR` 配下の命名規約のみによる自動選択（YAGNI）。

---

## ファイル構成

| ファイル | 責務 |
| -------- | ---- |
| [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py) | `digest_template_weekly_path` / `digest_template_monthly_path`（`str \| None`）と env 説明 |
| [`src/vcenter_event_assistant/services/digest_markdown.py`](../../src/vcenter_event_assistant/services/digest_markdown.py) | `_load_default_template_source` 抽出、`kind` 付き `_load_template_source`、`render_digest_markdown` から利用 |
| [`tests/test_digest_markdown.py`](../../tests/test_digest_markdown.py) | 週次・月次パス・フォールバック・エラーのテスト |
| [`.env.example`](../../.env.example) | 新 env のコメント（解決順の 1 行追記） |
| [`docs/development.md`](../../docs/development.md) | Batch digest 節に 1〜2 文（任意だが推奨） |

---

### Task 0: ブランチ（任意）

- [ ] **Step 1:** `main` を最新にし、作業ツリーがクリーンか確認する。

Run:

```bash
git status
git checkout main && git pull
```

Expected: 未コミットの無関係な変更がないこと。

- [ ] **Step 2:** フィーチャーブランチを切る（例: `feat/digest-weekly-monthly-templates`）。

```bash
git checkout -b feat/digest-weekly-monthly-templates
```

---

### Task 1: 週次・月次テンプレ解決（TDD：Settings + `digest_markdown` 一連）

**Files:**

- Modify: [`tests/test_digest_markdown.py`](../../tests/test_digest_markdown.py)（**最初に**手を入れる）
- Modify: [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py)
- Modify: [`src/vcenter_event_assistant/services/digest_markdown.py`](../../src/vcenter_event_assistant/services/digest_markdown.py)
- Modify: [`.env.example`](../../.env.example)（GREEN 後でよい）

**Settings 仕様（確定）:**

- `digest_template_weekly_path: str | None` — `DIGEST_TEMPLATE_WEEKLY_PATH`。**空（未設定または空白のみ）**は未指定。
- `digest_template_monthly_path: str | None` — `DIGEST_TEMPLATE_MONTHLY_PATH`。同様。
- `Field` の `description`: 非空かつ対応する `kind` のときだけそのファイルを最優先。ファイル不可はエラー。空のときは既存の **`DIGEST_TEMPLATE_PATH` → `DIR`+`FILE` → 同梱**。

`.env.example` は **テストがグリーンになったあと**、次の解決順をコメントで追記する:

1. `kind` が `weekly` かつ `DIGEST_TEMPLATE_WEEKLY_PATH` 非空 → そのファイル。
2. `kind` が `monthly` かつ `DIGEST_TEMPLATE_MONTHLY_PATH` 非空 → そのファイル。
3. それ以外 → 既存の単一解決チェーン。

- [ ] **Step 1（Red）:** [`tests/test_digest_markdown.py`](../../tests/test_digest_markdown.py) に、下記「テストケース」に対応する **`describe` / `test_*` を先に追加**する。`_minimal_settings(digest_template_weekly_path=..., digest_template_monthly_path=...)` のように **新フィールドを渡す**。この時点では Settings にフィールドが無いなら **`TypeError` / 予期しない引数**で FAIL、あっても `digest_markdown` 未対応なら **AssertionError** で FAIL することを確認する。

Run:

```bash
cd /Users/moriyama/git/vcenter-event-assistant && uv run pytest tests/test_digest_markdown.py -v
```

Expected: **新規テストを含め FAIL**（Red）。

- [ ] **Step 2（Green その1）:** [`settings.py`](../../src/vcenter_event_assistant/settings.py) に **`digest_template_weekly_path` / `digest_template_monthly_path` を最小追加**し、再度 pytest。まだ **`digest_markdown` が未実装なら** 振る舞いのテストは **FAIL のまま**（Red 継続）であること。

- [ ] **Step 3（Green その2）:** 下記 **リファクタ方針**どおり [`digest_markdown.py`](../../src/vcenter_event_assistant/services/digest_markdown.py) を実装し、**全テスト PASS**（Green）。

**リファクタ方針（実装内容）:**

- 現行の [`_load_template_source`](../../src/vcenter_event_assistant/services/digest_markdown.py) の本体（PATH → DIR+FILE → 同梱）を **`_load_default_template_source(settings: Settings) -> str`** にリネームまたは抽出する。
- 新規 **`_load_template_source(settings: Settings, *, kind: str) -> str`**:
  - `_strip_opt(settings.digest_template_weekly_path)` が非空 **かつ** `kind == "weekly"` → `Path(...).read_text`。**`is_file()` が False** なら `FileNotFoundError`（メッセージは既存の PATH 分岐に揃える）。
  - `_strip_opt(settings.digest_template_monthly_path)` が非空 **かつ** `kind == "monthly"` → 同様。
  - それ以外 → `_load_default_template_source(settings)`。
- `render_digest_markdown` 内の `source = _load_template_source(settings)` を `source = _load_template_source(settings, kind=kind)` に変更。

**Step 1 で追加するテストケース（`_minimal_settings` と最小 `DigestContext` は既存テストを流用）:**

1. **週次パス使用:** `tmp_path / "w.j2"` に `"# WEEKLY_ONLY\n"` を書き、`digest_template_weekly_path=str(w.j2)`、`kind="weekly"` → 出力に `WEEKLY_ONLY`。
2. **週次パスは daily では使わない:** 同じ設定で `kind="daily"` → 同梱またはデフォルトの見出し（例: `# vCenter ダイジェスト（日次）`）が含まれ、`WEEKLY_ONLY` は **含まれない**。
3. **週次未設定は従来 DIR:** `digest_template_dir` + `digest_template_file` のみ（週次パス空）、`kind="weekly"` → 既存 `test_render_digest_markdown_uses_digest_template_dir` と同様にカスタム内容が出る。
4. **週次パスが無効ファイル:** `digest_template_weekly_path="/nonexistent/weekly.j2"`、`kind="weekly"` → `pytest.raises(FileNotFoundError)`。
5. **月次:** (1)(2)(4) の `monthly` 版を同様に（ファイル名は `m.j2`、`MONTHLY_ONLY` など）。

- [ ] **Step 4:** [`.env.example`](../../.env.example) を更新（上記「Settings 仕様」の解決順コメント）。

- [ ] **Step 5:** 回帰確認。

Run:

```bash
cd /Users/moriyama/git/vcenter-event-assistant && uv run pytest tests/test_digest_markdown.py tests/test_digest_run.py tests/test_digests_api.py -v
```

Expected: **PASS**。

- [ ] **Step 6: Commit**（例: 機能 1 コミットにまとめるか、`settings` + テスト + `digest_markdown` で分割するかは任意）

```bash
git add src/vcenter_event_assistant/settings.py src/vcenter_event_assistant/services/digest_markdown.py tests/test_digest_markdown.py .env.example
git commit -m "feat(digest): optional weekly/monthly template paths by kind"
```

---

### Task 2: ドキュメント（短文）

**Files:**

- Modify: [`docs/development.md`](../../docs/development.md)（Batch digest / テンプレの節）

**前提:** Task 1 が **pytest グリーン**したあとに記述する（ドキュメント先行はしない）。

- [ ] **Step 1:** 週次・月次専用 `DIGEST_TEMPLATE_*_PATH` とフォールバック規則を 2〜4 文で追記する。
- [ ] **Step 2: Commit**

```bash
git add docs/development.md
git commit -m "docs: document per-kind digest template env vars"
```

---

## 完了時の検証コマンド（一覧）

```bash
cd /Users/moriyama/git/vcenter-event-assistant
uv run pytest tests/test_digest_markdown.py tests/test_digest_run.py -v
uv run ruff check src/vcenter_event_assistant/services/digest_markdown.py src/vcenter_event_assistant/settings.py
```

（プロジェクトで `ruff format` / `mypy` を必須にしている場合は README に従う。）

---

## Plan review loop（エージェント向け）

1. 本ファイルを **plan-document-reviewer** サブエージェントに渡しレビューする（本ファイルパスと関連ソースパスを明示。セッション履歴に頼らない）。
2. 指摘があれば本ファイルを修正し、最大 3 回まで再レビュー。
3. 人間レビュー後、実装へ進む。

---

## 実装完了後の進め方（人間向け）

Plan complete and saved to [`docs/superpowers/plans/2026-03-28-digest-per-kind-templates.md`](2026-03-28-digest-per-kind-templates.md).

**実行オプション:**

1. **Subagent-Driven（推奨）** — タスクごとに新しいサブエージェントを起動し、タスク間にレビュー。 `**@superpowers:subagent-driven-development**` を必須とする。
2. **Inline Execution** — 同一セッションで `**@superpowers:executing-plans**` に従いチェックポイント付きで一括実行。

どちらで進めますか。

