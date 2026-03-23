# ダイジェスト Jinja2 外部テンプレート Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 承認済み設計（[`docs/superpowers/specs/2026-03-23-digest-markdown-template-design.md`](../../specs/2026-03-23-digest-markdown-template-design.md)）に従い、ダイジェスト本文を **Jinja2 テンプレートファイル**から生成し、**環境変数でパス・表示 TZ を切り替え**、テンプレ失敗時は **`DigestRecord.status=error`** とする。

**Architecture:** `Settings` にテンプレート解決用・`DIGEST_DISPLAY_TIMEZONE` を追加する。同梱 `digest.md.j2` は **`importlib.resources`** で読み、外部パスは **`run_digest_once` ごとに `Path.read_text(encoding="utf-8")`**。Jinja `Environment` に **`fmt_ts` フィルタ**（`zoneinfo.ZoneInfo`）を登録し、コンテキストは `kind`・`ctx`（`DigestContext.model_dump(mode="json")`）・`display_timezone`（IANA 文字列）。`digest_run.run_digest_once` は **`render_template_digest` を廃止**し、新関数で Markdown を生成。集約（`digest_context`）と LLM（`digest_llm`）の契約は維持する。

**Tech Stack:** Python 3.12+、`jinja2`、`pydantic-settings`、既存 pytest-asyncio。

**参照 Spec:** [`docs/superpowers/specs/2026-03-23-digest-markdown-template-design.md`](../../specs/2026-03-23-digest-markdown-template-design.md)

---

## ファイル構成（作成・変更）

| ファイル | 責務 |
|----------|------|
| [`pyproject.toml`](../../pyproject.toml) | `jinja2` 依存を追加（`uv add jinja2`）。 |
| [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py) | `digest_template_path` / `digest_template_dir` / `digest_template_file` / `digest_display_timezone` を `Field` で定義（env 名は spec の `DIGEST_*` に合わせる）。 |
| **Create:** `src/vcenter_event_assistant/templates/digest.md.j2` | 現行 [`digest_markdown.py`](../../src/vcenter_event_assistant/services/digest_markdown.py) の出力と**同等**の Markdown（H1 は `# vCenter ダイジェスト（{{ kind }}）`、リストは `[:20]` などテンプレ内スライス）。 |
| [`src/vcenter_event_assistant/services/digest_markdown.py`](../../src/vcenter_event_assistant/services/digest_markdown.py) | テンプレート解決・読込・Jinja レンダリング・`fmt_ts`。**公開 API** は例: `render_digest_markdown(ctx, *, kind: str, settings: Settings) -> str`（失敗時は **例外**）。旧 `render_template_digest(..., title=...)` は **削除**する。 |
| [`src/vcenter_event_assistant/services/digest_run.py`](../../src/vcenter_event_assistant/services/digest_run.py) | `build_digest_context` → `render_digest_markdown` → `augment_digest_with_llm`。テンプレ段階で例外なら **`DigestRecord(status="error", error_message=..., body_markdown="" または短い説明)`** を追加して return（**LLM は呼ばない**）。既存の「LLM 失敗は ok」の方針は維持。 |
| [`tests/test_digest_markdown.py`](../../tests/test_digest_markdown.py) | 新シグネチャ・同梱テンプレ・（任意）一時ファイル上書き。 |
| [`tests/test_digest_run.py`](../../tests/test_digest_run.py) | 成功パス更新。**不正テンプレで `status=error`** を 1 ケース追加（`tmp_path` に壊れた `.j2` を置き `Settings` で指す）。 |
| **Create（任意）:** `tests/test_digest_template_resolve.py` | 解決順の単体テストが `test_digest_markdown.py` に収まらない場合のみ分割。 |
| [`.env.example`](../../.env.example) | `DIGEST_TEMPLATE_*` / `DIGEST_DISPLAY_TIMEZONE` をコメント例で追記。 |
| [`docs/development.md`](../../docs/development.md) | バッチダイジェスト節に「テンプレ解決順・次回実行から反映・集計 UTC・表示 TZ」を追記。 |

---

## Task 1: 依存 `jinja2`

**Files:**
- Modify: [`pyproject.toml`](../../pyproject.toml)（`uv` が更新）
- Modify: [`uv.lock`](../../uv.lock)（自動）

- [ ] **Step 1: 依存追加**

Run:

```bash
cd /path/to/vcenter-event-assistant && uv add jinja2
```

Expected: `pyproject.toml` に `jinja2` が追加される。

- [ ] **Step 2: コミット**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add jinja2 for digest templates"
```

---

## Task 2: `Settings` にダイジェストテンプレート・表示 TZ

**Files:**
- Modify: [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py)

- [ ] **Step 1: フィールド追加**（`Field` の `description` は日本語可・プロジェクト規約に合わせる）

```python
digest_template_path: str | None = Field(default=None, description="...")
digest_template_dir: str | None = Field(default=None, description="...")
digest_template_file: str = Field(default="digest.md.j2", description="...")
digest_display_timezone: str = Field(default="UTC", description="IANA。無効時は UTC にフォールバック。")
```

環境変数名は Pydantic のデフォルト（大文字アンダースコア）で `DIGEST_TEMPLATE_PATH` 等になることを確認する。

- [ ] **Step 2: 既存テストが通るか確認**

Run: `uv run pytest tests/test_digest_run.py tests/test_digest_markdown.py -q`

Expected: PASS（まだ未使用なら挙動不変）。

- [ ] **Step 3: コミット**

```bash
git add src/vcenter_event_assistant/settings.py
git commit -m "feat(settings): add digest template and display timezone options"
```

---

## Task 3: 同梱テンプレート `digest.md.j2`

**Files:**
- Create: [`src/vcenter_event_assistant/templates/digest.md.j2`](../../src/vcenter_event_assistant/templates/digest.md.j2)

- [ ] **Step 1: 現行 `digest_markdown.py` の出力と同等の Jinja を書く**

要件:
- 1 行目付近で `# vCenter ダイジェスト（{{ kind }}）`（コードから `title` は渡さない）。
- 期間・件数・表・要注意イベント・CPU/メモリは現行と同じ情報を出す。
- 要注意イベントは `{% for ev in ctx.top_notable_events[:20] %}` のように **テンプレ内でスライス**。
- 日時は `{{ ctx.from_utc | fmt_ts }}` 形式（フィルタは次タスクで実装）。

- [ ] **Step 2: パッケージに含まれるよう `pyproject.toml` の package-data または hatch/setuptools の設定を確認**

`vcenter_event_assistant` が `templates/*.j2` をホイールに含めること。既存のパッケージレイアウト（`src/`）に合わせ、`importlib.resources.files("vcenter_event_assistant") / "templates" / "digest.md.j2"` で読めるようにする。

- [ ] **Step 3: コミット**

```bash
git add src/vcenter_event_assistant/templates/digest.md.j2 pyproject.toml
git commit -m "feat(digest): add bundled digest.md.j2 template"
```

---

## Task 4: `digest_markdown.py` — 解決・`fmt_ts`・レンダリング

**Files:**
- Modify: [`src/vcenter_event_assistant/services/digest_markdown.py`](../../src/vcenter_event_assistant/services/digest_markdown.py)

- [ ] **Step 1: 失敗するテストを先に書く（TDD）**

[`tests/test_digest_markdown.py`](../../tests/test_digest_markdown.py) を、新 API に合わせて書き換える。

```python
def test_render_digest_markdown_uses_kind_not_title():
    # DigestContext は既存フィクスチャ同様に最小構築
    # settings = Settings(..., database_url=..., llm_api_key=None)  # テンプレ関連はデフォルト
    # md = render_digest_markdown(ctx, kind="daily", settings=settings)
    # assert "# vCenter ダイジェスト（daily）" in md
    # assert "42" in md
    pass
```

Run: `uv run pytest tests/test_digest_markdown.py -v`

Expected: **FAIL**（関数名未定義など）。

- [ ] **Step 2: 解決関数を実装**

解決順（spec 厳守）:

1. `digest_template_path` が非空 → そのパスが **ファイルとして存在**すればその内容を使用。存在しなければ **例外**（または spec に合わせてフォールバック — spec は「無効なら次」ではなく PATH 優先なので、**存在しない場合は明確に失敗**でよい。設計書「未設定または無効なら」は PATH が空のときの話。実装メモ: **PATH 指定かつファイルなし → エラー**）。

2. `digest_template_dir` が非空 → `Path(dir) / digest_template_file` を読む。

3. それ以外 → `importlib.resources` で同梱 `digest.md.j2` を読む。

各ステップで **UTF-8** で全文読み込み（**毎回**）。

- [ ] **Step 3: `fmt_ts` フィルタ**

- `settings.digest_display_timezone` を `ZoneInfo` に変換。無効なら **`logging.warning`** のうえ **UTC**。
- 入力: `str`（ISO）または `datetime` をパースして UTC に正規化し、表示 TZ に変換。
- 出力形式は **1 種類に固定**（例: `%Y-%m-%dT%H:%M:%S%z` または offset 付き ISO）。テストで文字列の一部を assert。

- [ ] **Step 4: `render_digest_markdown`**

```python
def render_digest_markdown(ctx: DigestContext, *, kind: str, settings: Settings) -> str:
    source = _load_template_source(settings)
    env = Environment(autoescape=False)  # Markdown なので False
    env.filters["fmt_ts"] = lambda v: _fmt_ts_filter(v, settings)
    tpl = env.from_string(source)
    ctx_dict = ctx.model_dump(mode="json")
    return tpl.render(kind=kind, ctx=ctx_dict, display_timezone=resolved_iana_string)
```

- [ ] **Step 5: テスト PASS**

Run: `uv run pytest tests/test_digest_markdown.py -v`

Expected: PASS

- [ ] **Step 6: コミット**

```bash
git add src/vcenter_event_assistant/services/digest_markdown.py tests/test_digest_markdown.py
git commit -m "feat(digest): render markdown from Jinja2 template and fmt_ts"
```

---

## Task 5: `digest_run.py` — 統合とテンプレ失敗時 `status=error`

**Files:**
- Modify: [`src/vcenter_event_assistant/services/digest_run.py`](../../src/vcenter_event_assistant/services/digest_run.py)

- [ ] **Step 1: `run_digest_once` を更新**

- `title = ...` と `render_template_digest(ctx, title=...)` を削除。
- `md = render_digest_markdown(ctx, kind=kind, settings=s)` を try/except で囲む。
- **成功**: 既存どおり `augment_digest_with_llm` → `status="ok"`。
- **テンプレ例外**: `DigestRecord(..., status="error", error_message=str(e)[:2000], body_markdown="", llm_model=None)` を追加して return（**flush まで**）。`error_message` は先頭に `digest template:` 等のプレフィックスを付けてもよい。

- [ ] **Step 2: テスト更新・追加**

[`tests/test_digest_run.py`](../../tests/test_digest_run.py): 既存成功ケースは新テンプレに合わせて assert 調整（`# vCenter ダイジェスト（daily）` など）。

新規:

```python
async def test_run_digest_once_template_error_sets_status_error(tmp_path):
    bad = tmp_path / "bad.j2"
    bad.write_text("{% unclosed", encoding="utf-8")
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key=None,
        digest_template_path=str(bad),
    )
    # ... DB に最低限データ ...
    # row = await run_digest_once(...)
    # assert row.status == "error"
    # assert row.body_markdown == ""  # またはポリシーに合わせる
```

- [ ] **Step 3: 実行**

Run: `uv run pytest tests/test_digest_run.py -v`

Expected: PASS

- [ ] **Step 4: コミット**

```bash
git add src/vcenter_event_assistant/services/digest_run.py tests/test_digest_run.py
git commit -m "feat(digest): wire Jinja template render and template error status"
```

---

## Task 6: 他テストの追随

**Files:**
- Modify: [`tests/test_digests_api.py`](../../tests/test_digests_api.py)（本文に H1 が含まれる assert があれば更新）
- Grep: `render_template_digest` / `title=` / 旧文言

- [ ] **Step 1: リポジトリ全体で参照を検索**

Run:

```bash
rg "render_template_digest" src tests
```

Expected: ゼロ件。

- [ ] **Step 2: 全テスト**

Run: `uv run pytest -q`

Expected: PASS

- [ ] **Step 3: コミット**（修正があれば）

```bash
git add tests/
git commit -m "test(digest): align with Jinja digest output"
```

---

## Task 7: ドキュメントと `.env.example`

**Files:**
- Modify: [`.env.example`](../../.env.example)
- Modify: [`docs/development.md`](../../docs/development.md)

- [ ] **Step 1: `.env.example`** に以下を追記（コメントで可）

- `DIGEST_TEMPLATE_PATH` / `DIGEST_TEMPLATE_DIR` / `DIGEST_TEMPLATE_FILE`
- `DIGEST_DISPLAY_TIMEZONE=UTC`（例: `Asia/Tokyo`）
- 解決順・相対パスは cwd 基準である旨

- [ ] **Step 2: `docs/development.md`** のバッチダイジェスト節に、上記と「集計は UTC、表示は `DIGEST_DISPLAY_TIMEZONE`」を追記。

- [ ] **Step 3: コミット**

```bash
git add .env.example docs/development.md
git commit -m "docs: document digest Jinja template env vars"
```

---

## Task 8: 検証（完了前必須）

@superpowers:verification-before-completion に従う。

- [ ] **Step 1: Lint**

Run: `uv run ruff check src tests`

Expected: 問題なし

- [ ] **Step 2: テスト**

Run: `uv run pytest -q`

Expected: すべて PASS

---

## Plan Review（任意）

リポジトリに `plan-document-reviewer-prompt.md` が無い場合、**人間レビュー**で計画と spec の整合を確認する。

---

## 実行引き渡し

実装完了後、以下から選択してください。

**Plan complete and saved to `docs/superpowers/plans/2026-03-23-digest-jinja-template.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — タスクごとに新しいサブエージェントを起動し、タスク間でレビューする（@superpowers:subagent-driven-development）。

2. **Inline Execution** — このセッションで @superpowers:executing-plans に従いチェックポイント付きで実行する。

どちらで進めますか？
