# ダイジェスト集計ウィンドウのタイムゾーン対応 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `DIGEST_DISPLAY_TIMEZONE` で指定した IANA タイムゾーン上の暦（日次・週次・月次）に沿ってダイジェスト集計の半開区間 `[period_start, period_end)` を決め、スケジューラ・手動 API のデフォルト期間と一致させる。API／DB に保存する瞬間は引き続き UTC。

**Architecture:** `digest_markdown` にある表示用 TZ 解決（無効名は UTC フォールバック＋警告）を **`digest_timezone.py` に集約**し、集計ウィンドウ計算とテンプレ表示の両方が同じ `ZoneInfo` を参照する。`digest_window.py` は `ZoneInfo` を引数に取る `zoned_*` 純関数を追加し、既存 `utc_*` は **`ZoneInfo("UTC")` に委譲**して既存テストをそのまま回帰できるようにする。`scheduler.py` と `POST /api/digests/run` は `get_settings()` から解決したゾーンで `zoned_*` を呼ぶ。手動 API は `from_time`/`to_time` 省略時に **`kind` に応じたデフォルト**（daily／weekly／monthly）を使う。

**Tech Stack:** Python 3.12+、`zoneinfo.ZoneInfo`、`uv run pytest`。フロント変更なし（別タスク）。

**要件出典:** brainstorming で合意（表示＋集計を同一 IANA に統一。週はその TZ で日曜 0:00 始まりの直前週、月はその TZ の直前暦月）。

---

## ファイル構成（変更・新規）

| ファイル | 役割 |
|----------|------|
| `src/vcenter_event_assistant/services/digest_timezone.py` | **新規** `resolve_digest_timezone(settings) -> tuple[ZoneInfo, str]`。ログ文言は既存 `digest_markdown._resolve_display_timezone` と互換（`test_digest_markdown` の警告検証が壊れないようにする）。 |
| `src/vcenter_event_assistant/services/digest_markdown.py` | `_resolve_display_timezone` を `digest_timezone` へ委譲（または削除して import）。 |
| `src/vcenter_event_assistant/services/digest_window.py` | `zoned_yesterday_window` / `zoned_previous_week_window` / `zoned_previous_calendar_month_window` を追加。`utc_*` は内部で `zoned_*(..., ZoneInfo("UTC"))` を呼ぶ。モジュール docstring を「UTC のみ」から更新。 |
| `src/vcenter_event_assistant/jobs/scheduler.py` | 各 `run_*_digest` で `resolve_digest_timezone(get_settings())` の `ZoneInfo` を `zoned_*` に渡す。 |
| `src/vcenter_event_assistant/api/routes/digests.py` | 期間省略時、`req.kind` に応じて `zoned_*` を切り替え。 |
| `src/vcenter_event_assistant/api/schemas.py` | `DigestRunRequest` の docstring を「省略時は設定 TZ に基づく種別ごとの直前期間」に更新。 |
| `src/vcenter_event_assistant/settings.py` | `digest_display_timezone` の description から「集計は UTC」を削除し、集計境界にも使う旨を日本語で記載。 |
| `.env.example` | 同上の説明を 1〜2 行追記または修正。 |
| `tests/test_digest_window.py` | 既存 `utc_*` テストは維持。`Asia/Tokyo` 等の **zoned 専用ケース**を追加。 |
| `tests/test_digest_markdown.py` | 警告ログ文言・挙動が変わらないことを確認（import 経路変更のみならそのまま）。 |
| `tests/test_digests_api.py` | 任意: `kind: weekly` かつ期間省略で `period_start`/`period_end` が zoned 週窓と一致するテスト（`freezegun` または settings オーバーライドが必要ならタスク内で方針を決める）。 |

**スコープ外:** イベント `/events/rate-series` の UTC エポックバケット、ログ `asctime` の TZ、フロント既定 TZ（将来タスク）。

---

## アルゴリズム（実装メモ）

- **`now` の正規化:** 既存と同様、省略時は `datetime.now(timezone.utc)`、渡された値は UTC に正規化。
- **日次（zoned）:** `local = now_utc.astimezone(tz)`、`d = local.date()` とし、`[combine(d-1, 00:00, tzinfo=tz), combine(d, 00:00, tzinfo=tz))` を UTC に変換。
- **週次（zoned）:** `start_today = combine(local.date(), 00:00, tzinfo=tz)`。`days_since_sunday = (start_today.weekday() + 1) % 7`（月曜=0…日曜=6）。`this_week_sunday = start_today - timedelta(days=days_since_sunday)`。戻りは `[this_week_sunday - 7d, this_week_sunday)` を UTC に変換。既存 UTC 版と同じ定義を **ローカル暦に置き換えたもの**。
- **月次（zoned）:** `first_this_month = start_today.replace(day=1)`、`last_prev = first_this_month - 1 day`、`first_prev_month = last_prev.replace(day=1)`。`[first_prev_month, first_this_month)` を UTC へ。

---

### Task 1: `digest_timezone.py` への解決ロジック集約

**Files:**
- Create: `src/vcenter_event_assistant/services/digest_timezone.py`
- Modify: `src/vcenter_event_assistant/services/digest_markdown.py`

- [ ] **Step 1:** `digest_timezone.py` に `resolve_digest_timezone(settings: Settings) -> tuple[ZoneInfo, str]` を実装。無効 IANA 時の **警告ログ文言**は `tests/test_digest_markdown.py` の `test_invalid_display_timezone_warns_and_falls_back` が期待する文字列（`無効な DIGEST_DISPLAY_TIMEZONE=...`）と一致させる。

- [ ] **Step 2:** `digest_markdown._resolve_display_timezone` を `resolve_digest_timezone` のラッパにするか、呼び出し側を差し替えて重複をなくす。

- [ ] **Step 3:** テスト実行

Run: `uv run pytest tests/test_digest_markdown.py -v`

Expected: すべて PASS

- [ ] **Step 4:** Commit

```bash
git add src/vcenter_event_assistant/services/digest_timezone.py src/vcenter_event_assistant/services/digest_markdown.py
git commit -m "refactor(digest): centralize timezone resolution in digest_timezone"
```

---

### Task 2: `digest_window` に `zoned_*` を追加し `utc_*` を委譲

**Files:**
- Modify: `src/vcenter_event_assistant/services/digest_window.py`
- Modify: `tests/test_digest_window.py`（後続タスクで東京ケース追加でも可）

- [ ] **Step 1:** `zoned_yesterday_window(now, tz: ZoneInfo)` ほか週次・月次を実装。内部で `datetime.combine` と `time.min`、`timedelta` を使用（`from __future__ import annotations` 維持）。

- [ ] **Step 2:** `utc_yesterday_window` 等は `zoned_*(..., ZoneInfo("UTC"))` を返すようリファクタ。

- [ ] **Step 3:** 回帰テスト

Run: `uv run pytest tests/test_digest_window.py -v`

Expected: 既存ケースすべて PASS（UTC 委譲が旧実装と一致すること）。

- [ ] **Step 4:** Commit

```bash
git add src/vcenter_event_assistant/services/digest_window.py
git commit -m "feat(digest): add zoned digest windows with UTC wrappers"
```

---

### Task 3: `Asia/Tokyo` などの境界テスト追加

**Files:**
- Modify: `tests/test_digest_window.py`

- [ ] **Step 1:** 少なくとも次を追加する（期待値は手計算で固定）:
  - 日次: `now` が UTC で「JST では翌日に跨ぐ」瞬間（例: 2026-03-22 15:00 UTC は JST 3/23 0:00）で、`Asia/Tokyo` の「昨日」が JST 3/22 一日になること。
  - 週次・月次: 各 1 ケース（東京または UTC で意図が分かるもの）。

- [ ] **Step 2:**

Run: `uv run pytest tests/test_digest_window.py -v`

Expected: PASS

- [ ] **Step 3:** Commit

```bash
git add tests/test_digest_window.py
git commit -m "test(digest): add Asia/Tokyo window boundaries"
```

---

### Task 4: スケジューラが `zoned_*` を使用

**Files:**
- Modify: `src/vcenter_event_assistant/jobs/scheduler.py`

- [ ] **Step 1:** `resolve_digest_timezone` と `zoned_*` を import。各 `run_*_digest` 内で `tz, _ = resolve_digest_timezone(get_settings())` を取得し、`utc_*` の代わりに `zoned_*(..., tz)` を呼ぶ。

- [ ] **Step 2:** 既存の digest 系テストがあれば実行

Run: `uv run pytest tests/ -k digest -v --tb=short`

Expected: FAIL がなければよい（新規失敗 0）。

- [ ] **Step 3:** Commit

```bash
git add src/vcenter_event_assistant/jobs/scheduler.py
git commit -m "feat(digest): use zoned windows in scheduler jobs"
```

---

### Task 5: `POST /api/digests/run` のデフォルト期間を `kind` 連動に変更

**Files:**
- Modify: `src/vcenter_event_assistant/api/routes/digests.py`
- Modify: `src/vcenter_event_assistant/api/schemas.py`

- [ ] **Step 1:** `digests.run_digest` で `from_time`/`to_time` が両方 `None` のとき、`req.kind` が `daily` / `weekly` / `monthly`（および将来の別名があれば定数化）に応じて適切な `zoned_*` を呼ぶ。未知の `kind` は **422 または 400** で明示（既存に合わせる）。

- [ ] **Step 2:** `DigestRunRequest` の docstring と Field description を更新。

- [ ] **Step 3:**

Run: `uv run pytest tests/test_digests_api.py -v`

Expected: PASS

- [ ] **Step 4:** Commit

```bash
git add src/vcenter_event_assistant/api/routes/digests.py src/vcenter_event_assistant/api/schemas.py
git commit -m "feat(api): default digest run windows by kind and configured TZ"
```

---

### Task 6: 設定・サンプル環境変数のドキュメント更新

**Files:**
- Modify: `src/vcenter_event_assistant/settings.py`
- Modify: `.env.example`

- [ ] **Step 1:** `digest_display_timezone` の説明を「ダイジェスト本文の日時表示 **および** 集計ウィンドウ（日／週／月）の暦境界」に更新。

- [ ] **Step 2:** `.env.example` の `DIGEST_DISPLAY_TIMEZONE` コメントを同趣旨に合わせる。

- [ ] **Step 3:** Commit

```bash
git add src/vcenter_event_assistant/settings.py .env.example
git commit -m "docs(settings): document digest TZ for aggregation windows"
```

---

### Task 7: 全体テストと仕上げ

- [ ] **Step 1:**

Run: `uv run pytest`

Expected: 全件 PASS

- [ ] **Step 2:** 変更があればフォーマット・リントに従い修正。

- [ ] **Step 3:** 必要なら `tests/test_digests_api.py` に `kind: weekly` のデフォルト窓テストを追加（省略可だが推奨）。

---

## Plan review loop

1. 本プランを `plan-document-reviewer` 相当のレビュー（別セッション可）に渡し、タスク順・抜け・テスト十分性を確認する。
2. 指摘があれば本ファイルを修正してから実装に入る。

---

## Execution handoff

プラン保存後の進め方:

1. **Subagent-Driven（推奨）** — タスクごとに新規サブエージェントを起動し、タスク間でレビュー（`superpowers:subagent-driven-development`）。
2. **インライン実行** — 同一セッションで `superpowers:executing-plans` に従いチェックポイント付きで一括実行。

どちらで進めるか選んでください。
