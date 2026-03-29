# ダイジェスト多頻度スケジュール実装計画

> **For agentic workers:** 本計画の実装は **`@superpowers:subagent-driven-development`**（タスク単位のサブエージェント + 二段レビュー）を既定とする。代替は `superpowers:executing-plans`。チェックボックス（`- [ ]`）で進捗を追う。
>
> **TDD 必須（実装者）:** `@superpowers:test-driven-development` に従う。**本番コードを書く前に必ず失敗するテストを書き、`uv run pytest` で意図どおり FAIL することを確認してから**最小実装で GREEN にする。テストが最初から PASS ならテストが無効なのでやり直す。リファクタは GREEN の後のみ。

**Goal:** 日次ダイジェストに加え、**週次**（UTC・日曜始まりの**直前に完了した暦週** 7 日）と**月次**（直前の UTC 暦月）を APScheduler で任意に有効化し、**種別ごとに cron** を環境変数で指定できるようにする。既存の `DIGEST_SCHEDULER_ENABLED` / `DIGEST_CRON` は**後方互換**として日次へ引き継ぐ。

**Architecture:** 集計ウィンドウは [digest_window.py](../../src/vcenter_event_assistant/services/digest_window.py) に純関数 `utc_previous_week_window` / `utc_previous_calendar_month_window` を追加する（既存 `utc_yesterday_window` と同様に `now` を注入可能）。[settings.py](../../src/vcenter_event_assistant/settings.py) に `digest_*_enabled` / `digest_*_cron` を種別ごとに追加し、旧フィールドから**有効フラグと cron の実効値**を決めるルールを 1 箇所にまとめる。[scheduler.py](../../src/vcenter_event_assistant/jobs/scheduler.py) は `digest_daily` / `digest_weekly` / `digest_monthly` の 3 ジョブを**それぞれ独立**に条件登録し、各ジョブは `run_digest_once(..., kind=..., from_utc=..., to_utc=...)` を呼ぶ。`POST /api/digests/run` の契約は変更不要（手動は従来どおり任意期間）。

**Tech Stack:** Python 3.12+、Pydantic v2 / pydantic-settings、APScheduler `CronTrigger.from_crontab`、pytest、既存の `run_digest_once` / `session_scope`。

**参照設計:** リポジトリ外の場合あり — ローカル `.cursor/plans/ダイジェスト多頻度スケジュール_dae9268f.plan.md`（週境界・非スコープの要約）。

---

## TDD サイクル（各タスク共通）

| 段階 | 行うこと | 検証 |
|------|----------|------|
| **RED** | 振る舞い 1 件につきテスト 1 本（関数名で意図が読める）。 | `uv run pytest <対象ファイル> -v` で **FAIL**。理由は「未実装 / アサーション不一致」であり、タイポや import エラーで止まっていないこと。 |
| **GREEN** | そのテストを通す**最小**の実装のみ。 | 同コマンドで **PASS**。 |
| **REFACTOR** | 重複削除・名前整理・ヘルパ抽出。 | テストは **引き続き PASS**（新しい振る舞いは足さない）。 |

**禁止:** テストなしでの `digest_window` / `settings` / スケジューラ登録ロジックの追加。「参考実装を先に書いてからテスト」も不可（スキルどおり削除してテストからやり直す）。

**例外（TDD の対象外）:** Task 5 の **`.env.example` / `docs/development.md` / 任意の Jinja** は設定・ドキュメントのため、失敗テストは不要。ただしテンプレや文言を**振る舞い変更**とみなすなら、該当するレンダリングの pytest を先に足す。

**完了前チェックリスト（実装者）**

- [ ] 新規関数・新規分岐ごとに、**先に FAIL を見た**テストがある
- [ ] `uv run pytest tests/ -q` が緑
- [ ] バグや仕様ずれは、再発テスト（RED）→ 修正（GREEN）で直す

---

## ファイル構成

| ファイル | 責務 |
|----------|------|
| `src/vcenter_event_assistant/services/digest_window.py` | `utc_previous_week_window`、`utc_previous_calendar_month_window`（UTC 正規化・半開区間 `[from,to)`） |
| `src/vcenter_event_assistant/settings.py` | 日次・週次・月次の `enabled` / `cron`、旧 `digest_scheduler_enabled` / `digest_cron` の互換、**実効値**用メソッドまたはプロパティ |
| `src/vcenter_event_assistant/jobs/scheduler.py` | 3 種の `add_job`、ログに `kind` と期間 |
| `tests/test_digest_window.py` | 週次・月次ウィンドウの境界テスト |
| `tests/test_digest_schedule_settings.py`（新規） | 実効 `enabled` / `cron` のユニットテスト（`Settings(...)` 直コンストラクトで十分なら env 不要） |
| `tests/test_digest_scheduler_jobs.py`（新規） | ダイジェスト用 APScheduler ジョブ登録の件数・`id`（Task 4・TDD 必須） |
| `src/vcenter_event_assistant/templates/digest.md.j2` | 任意: H1 の `kind` を日次/週次/月次の日本語ラベルに（現状は `{{ kind }}` のままでも動作する） |
| `.env.example` | 新 env 名と cron 例・曜日の注意 |
| `docs/development.md` | バッチダイジェスト節へスケジュール説明を追記 |

---

## 期間定義（実装必須）

### 週次 `utc_previous_week_window(now)`

- `n` = `now` を timezone-aware UTC に正規化（`utc_yesterday_window` と同パターン）。
- `today_start` = `n` の暦日 0:00 UTC。
- `this_week_sunday` = `today_start - timedelta(days=(today_start.weekday() + 1) % 7)`  
  （Python `weekday()`: 月曜=0 … 日曜=6）
- 戻り値: `(this_week_sunday - timedelta(days=7), this_week_sunday)` → **ちょうど 7 日間の半開区間**。

### 月次 `utc_previous_calendar_month_window(now)`

- `today_start` 同上。
- `first_this` = `today_start.replace(day=1)`。
- `first_prev` = `(first_this - timedelta(days=1)).replace(day=1)`。
- 戻り値: `(first_prev, first_this)`。

---

## 設定の実効ルール（後方互換）

スケジューラは次の**実効値**だけを参照する（実装は `Settings` のメソッド 2 本に集約すると読みやすい）。

**日次**

- `effective_digest_daily_enabled` = `digest_daily_enabled or digest_scheduler_enabled`
- `effective_digest_daily_cron` =  
  - `digest_daily_enabled` が True なら **`digest_daily_cron`**  
  - そうでなく `digest_scheduler_enabled` が True なら **`digest_cron`**  
  - それ以外は参照しない（ジョブ未登録）

**週次 / 月次**

- それぞれ `digest_weekly_enabled` / `digest_weekly_cron`、`digest_monthly_enabled` / `digest_monthly_cron` をそのまま使用。

**新規フィールド（提案デフォルト）**

| フィールド | 環境変数例 | 既定 |
|------------|------------|------|
| `digest_daily_enabled` | `DIGEST_DAILY_ENABLED` | `False` |
| `digest_daily_cron` | `DIGEST_DAILY_CRON` | `"0 7 * * *"` |
| `digest_weekly_enabled` | `DIGEST_WEEKLY_ENABLED` | `False` |
| `digest_weekly_cron` | `DIGEST_WEEKLY_CRON` | `"0 8 * * 0"`（月曜 8:00。APScheduler は 0=月曜…6=日曜） |
| `digest_monthly_enabled` | `DIGEST_MONTHLY_ENABLED` | `False` |
| `digest_monthly_cron` | `DIGEST_MONTHLY_CRON` | `"5 0 1 * *"` |

`digest_scheduler_enabled` / `digest_cron` の `Field.description` に**非推奨**と上記マッピングを日本語で明記する。

**APScheduler の曜日:** `CronTrigger.from_crontab` の 5 フィールド目は **Python weekday 準拠（0=月曜…6=日曜）**。Unix cron の **0/7=日曜とは異なり、7 は無効**。既定の週次例は月曜 `"0 8 * * 0"`、日曜に合わせるなら `"0 8 * * 6"`。時刻は `timezone` 未指定時はローカル TZ で解釈。

---

### Task 1: `utc_previous_week_window` のテストと実装

**Files:**

- Modify: [src/vcenter_event_assistant/services/digest_window.py](../../src/vcenter_event_assistant/services/digest_window.py)
- Modify: [tests/test_digest_window.py](../../tests/test_digest_window.py)

- [ ] **Step 1: 失敗するテストを書く**

  少なくとも次のケース（`now` はすべて `timezone.utc`）:

  1. **水曜** `2026-03-25 12:00` → 今週日曜は `2026-03-22`、前週は `[2026-03-15 00:00, 2026-03-22 00:00)`。
  2. **日曜** `2026-03-22 10:00` → `[2026-03-15 00:00, 2026-03-22 00:00)`。
  3. **月曜** `2026-03-23 00:00` → 今週日曜は `2026-03-22`、前週は `[2026-03-15 00:00, 2026-03-22 00:00)`。  
  4. **日曜境界** `2026-03-21 23:59 UTC`（土曜）では `to = 2026-03-15 00:00`（当該週の日曜は 3/15）、`2026-03-22 00:01 UTC`（日曜直後）では `to = 2026-03-22 00:00` となること。**日付が跨ぐと属する週が変わる**ことをこの 2 点で固定する。

```python
# tests/test_digest_window.py に追加（例）
from datetime import datetime, timezone
from vcenter_event_assistant.services.digest_window import utc_previous_week_window

def test_previous_week_window_wednesday() -> None:
    now = datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc)
    fr, to = utc_previous_week_window(now)
    assert fr == datetime(2026, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert to == datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    assert fr < to
```

- [ ] **Step 2: テスト実行（FAIL を確認）**

  Run: `uv run pytest tests/test_digest_window.py -v`

  Expected: `ImportError` または未定義で FAIL。

- [ ] **Step 3: `utc_previous_week_window` を実装**

  上記「期間定義」の式どおり。docstring は日本語で半開区間と日曜始まりを明記。

- [ ] **Step 4: テスト PASS**

  Run: `uv run pytest tests/test_digest_window.py -v`

- [ ] **Step 5（REFACTOR・任意）:** 重複する UTC 正規化があれば `digest_window` 内の小さな `_to_utc_day_start` 等にまとめる。テストは緑のまま。

- [ ] **Step 6: コミット**

```bash
git add src/vcenter_event_assistant/services/digest_window.py tests/test_digest_window.py
git commit -m "feat(digest): add utc_previous_week_window (UTC Sunday week)"
```

（Task 1 の Step 1 は、テストを**1 本ずつ**追加し、その都度 RED→GREEN してもよい。まとめて複数 assert を書く場合でも、**最初の `pytest` は必ず FAIL を見る**。）

---

### Task 2: `utc_previous_calendar_month_window` のテストと実装

**Files:**

- Modify: [src/vcenter_event_assistant/services/digest_window.py](../../src/vcenter_event_assistant/services/digest_window.py)
- Modify: [tests/test_digest_window.py](../../tests/test_digest_window.py)

- [ ] **Step 1: 失敗するテスト**

  1. `2026-03-15` → `[2026-02-01, 2026-03-01)`  
  2. `2026-03-01 08:00` → 同上（当月 1 日でも先月は 2 月）  
  3. `2024-03-10`（うるう年翌月）→ `[2024-02-01, 2024-03-01)`  
  4. **年跨ぎ** `2026-01-10` → `[2025-12-01, 2026-01-01)`

- [ ] **Step 2:** `uv run pytest tests/test_digest_window.py -v` → FAIL

- [ ] **Step 3:** `utc_previous_calendar_month_window` を実装

- [ ] **Step 4:** `uv run pytest tests/test_digest_window.py -v` → PASS

- [ ] **Step 5: コミット**

```bash
git add src/vcenter_event_assistant/services/digest_window.py tests/test_digest_window.py
git commit -m "feat(digest): add utc_previous_calendar_month_window"
```

---

### Task 3: Settings の新フィールドと実効ルール

**Files:**

- Modify: [src/vcenter_event_assistant/settings.py](../../src/vcenter_event_assistant/settings.py)
- Create: [tests/test_digest_schedule_settings.py](../../tests/test_digest_schedule_settings.py)

- [ ] **Step 1: 失敗するテスト**

  `Settings` をコンストラクタで直接生成（env に依存させない）。

```python
# tests/test_digest_schedule_settings.py
from vcenter_event_assistant.settings import Settings

def test_effective_daily_uses_new_when_daily_enabled() -> None:
    s = Settings(
        digest_daily_enabled=True,
        digest_daily_cron="1 2 * * *",
        digest_scheduler_enabled=True,
        digest_cron="9 9 * * *",
    )
    assert s.effective_digest_daily_enabled is True
    assert s.effective_digest_daily_cron == "1 2 * * *"

def test_effective_daily_legacy_only() -> None:
    s = Settings(
        digest_daily_enabled=False,
        digest_scheduler_enabled=True,
        digest_cron="0 6 * * *",
        digest_daily_cron="0 7 * * *",
    )
    assert s.effective_digest_daily_enabled is True
    assert s.effective_digest_daily_cron == "0 6 * * *"

def test_effective_daily_both_disabled() -> None:
    s = Settings(digest_daily_enabled=False, digest_scheduler_enabled=False)
    assert s.effective_digest_daily_enabled is False
```

  メソッド名は実装に合わせてよいが、スケジューラは**この実効 API だけ**を呼ぶこと。

- [ ] **Step 2:** `uv run pytest tests/test_digest_schedule_settings.py -v` → FAIL

- [ ] **Step 3:** `settings.py` にフィールド追加 + `@property` またはメソッドで実効値（上記互換ルールどおり）。`digest_scheduler_enabled` / `digest_cron` の description に非推奨注記。

- [ ] **Step 4:** `uv run pytest tests/test_digest_schedule_settings.py -v` → PASS

- [ ] **Step 5:** `uv run pytest tests/ -q` で既存が壊れていないことを確認

- [ ] **Step 6: コミット**

```bash
git add src/vcenter_event_assistant/settings.py tests/test_digest_schedule_settings.py
git commit -m "feat(settings): digest daily/weekly/monthly schedule flags and legacy mapping"
```

---

### Task 4: APScheduler に週次・月次ジョブを追加

**Files:**

- Modify: `src/vcenter_event_assistant/jobs/scheduler.py`
- Create: `tests/test_digest_scheduler_jobs.py`

**TDD:** ジョブ登録ロジックに**先に**テストを付ける。`setup_scheduler` 全体を動かすとイベント取り込みジョブも載るため、**ダイジェストジョブだけ**を登録する関数を `scheduler.py` に切り出すと検証しやすい（例: `add_digest_cron_jobs(scheduler: AsyncIOScheduler, settings: Settings) -> None`）。`setup_scheduler` は既存どおり `poll_events` 等の後にこの関数を呼ぶ。

- [ ] **Step 1（RED）:** `tests/test_digest_scheduler_jobs.py` を追加。`AsyncIOScheduler()` を生成し（`start` は不要ならしない）、代表ケースで **登録されるジョブの `id` 集合**を検証する。

  最低限のケース例:

  1. 日次のみ有効（新 `effective` またはレガシーのみ True）→ `digest_daily` のみ。
  2. 週次・月次も True → `digest_daily`, `digest_weekly`, `digest_monthly` の 3 つ。
  3. いずれのダイジェストも無効 → ダイジェスト系 `id` は 0 件。

  この時点で `add_digest_cron_jobs` が未存在、または旧実装のため期待と不一致で **FAIL** することを `uv run pytest tests/test_digest_scheduler_jobs.py -v` で確認。

- [ ] **Step 2（GREEN）:** `scheduler.py` に `add_digest_cron_jobs`（名称は実装でよい）を実装し、`setup_scheduler` から呼ぶ。`utc_previous_week_window` / `utc_previous_calendar_month_window` を import。`run_daily_digest` の登録条件を **`effective_digest_daily_enabled` / `effective_digest_daily_cron`** に差し替え。`run_weekly_digest` / `run_monthly_digest` を追加し、週次・月次は新 `enabled` / `cron` で `add_job`。

```python
async def run_weekly_digest() -> None:
    fr, to = utc_previous_week_window()
    try:
        async with session_scope() as session:
            row = await run_digest_once(
                session,
                kind="weekly",
                from_utc=fr,
                to_utc=to,
                settings=get_settings(),
            )
        logger.info(
            "digest created kind=weekly id=%s period=%s..%s",
            row.id,
            fr.isoformat(),
            to.isoformat(),
        )
    except Exception:
        logger.exception("weekly digest job failed")
```

- [ ] **Step 3（GREEN 確認）:** `uv run pytest tests/test_digest_scheduler_jobs.py -v` → PASS。

- [ ] **Step 4:** `uv run pytest tests/ -q` で全テスト緑。

- [ ] **Step 5（REFACTOR・任意）:** ジョブ関数の重複（try/except/log）を共通化してもよい。`test_digest_scheduler_jobs` が緑のままであること。

- [ ] **Step 6: コミット**

```bash
git add src/vcenter_event_assistant/jobs/scheduler.py tests/test_digest_scheduler_jobs.py
git commit -m "feat(scheduler): register weekly and monthly digest cron jobs"
```

---

### Task 5: テンプレート（任意）・ドキュメント

**Files:**

- Modify（任意）: [src/vcenter_event_assistant/templates/digest.md.j2](../../src/vcenter_event_assistant/templates/digest.md.j2)
- Modify: [.env.example](../../.env.example)
- Modify: [docs/development.md](../../docs/development.md)

- [ ] **Step 1（任意）:** H1 を `daily` / `weekly` / `monthly` で日本語化（Jinja の `if`）。未実施でも機能上は問題なし。

- [ ] **Step 2:** `.env.example` の Batch digest 節に `DIGEST_DAILY_*` / `DIGEST_WEEKLY_*` / `DIGEST_MONTHLY_*` と、旧変数の非推奨・マッピング、cron 5 フィールド、**APScheduler の曜日（0=月曜…6=日曜）**を日本語コメントで記載。

- [ ] **Step 3:** `docs/development.md` に「日次・週次・月次の自動実行は env で ON/OFF と cron」「週次は UTC 日曜始まりの前週」「月次は直前の UTC 暦月」を短く追記。

- [ ] **Step 4: コミット**

```bash
git add .env.example docs/development.md src/vcenter_event_assistant/templates/digest.md.j2
git commit -m "docs: document multi-cadence digest scheduler env"
```

---

## 手動検証（推奨）

1. `.env` で `DIGEST_WEEKLY_ENABLED=true`、`DIGEST_WEEKLY_CRON` を数分先に設定し、アプリ起動後ログに `kind=weekly` と期待する `period` が出ることを確認。
2. `CronTrigger.from_crontab` の曜日フィールドが期待どおりか、REPL または短いスクリプトで確認。

---

## 非スコープ

- `GET /api/config` へのスケジュール露出（YAGNI）。
- 同一 `[from,to)`・同一 `kind` の重複レコード防止（DB ユニーク等）。
- フロントの設定 UI。

---

## 計画レビュー（スキル手順）

1. `plan-document-reviewer` サブエージェントに、**本ファイルのパス**と**設計メモ**（上記 `.cursor/plans/...`）のみを渡してレビュー依頼する。
2. 指摘があれば本計画を修正し、最大 3 回まで再レビュー。
3. 承認後、実装へ進む。

---

## 実行方式: Subagent-Driven Development（本計画の推奨ルート）

オーケストレーター（このリポで実装を進めるエージェント／人間）は、次の順序を**守る**。スキル原文: `@superpowers:subagent-driven-development`。

### 開始前（必須）

1. **`@superpowers:using-git-worktrees`** に従い、**main/master 直叩きせず**作業用ブランチまたはワークツリーで着手する（人間の明示同意なしに main で実装しない）。
2. 本ファイルから **Task 1〜5 の見出しとチェックリスト全文**を抽出し、オーケストレーター側の Todo / メモに載せる。

### タスクごとのループ（Task 1 → 5 を順に。実装サブエージェントの並列起動は禁止）

各タスクで、サブエージェントに渡すのは **当該 Task セクションの全文 + 本節の TDD 要件 + リポジトリルート**である。スキルどおり、**実装者に計画ファイルを読ませず**、必要な文脈はオーケストレーターが貼る。

| 順序 | 役割 | 内容 |
|------|------|------|
| 1 | **実装者** | `implementer-prompt.md` に相当する指示で実装。`@superpowers:test-driven-development` 厳守。`uv run pytest` で緑まで確認し、**当該タスク分をコミット**。自己レビュー。返却ステータス: `DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`。 |
| 2 | **仕様適合レビュー** | `spec-reviewer-prompt.md` に相当。本計画の当該 Task の要件だけに照らし合わせる。**先にこちらを通す（コード品質レビューより前）**。❌ なら実装者が修正 → 再レビュー。 |
| 3 | **コード品質レビュー** | `code-quality-reviewer-prompt.md` に相当。仕様 ✅ の後だけ実行。❌ なら実装者が修正 → 再レビュー。 |

**禁止:** 仕様レビューをスキップして品質レビューだけ行う、指摘が残ったまま次タスクへ進む、複数タスク用の実装サブエージェントを同時起動する。

**プロンプト雛形の場所（Cursor 同梱スキル）:**  
`~/.cursor/plugins/cache/cursor-public/superpowers/8ea39819eed74fe2a0338e71789f06b30e953041/skills/subagent-driven-development/` 内の `implementer-prompt.md` / `spec-reviewer-prompt.md` / `code-quality-reviewer-prompt.md`。

### 全タスク完了後

1. **最終コードレビュー**（実装全体）を 1 回。
2. **`@superpowers:finishing-a-development-branch`** に従い、マージ方針・PR・ブランチ整理を決める。

### 代替ルート

同一セッションでまとめて進める場合のみ **`@superpowers:executing-plans`**。その場合も TDD と本計画の Task 境界は維持する。
