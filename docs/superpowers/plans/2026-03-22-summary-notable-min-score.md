# 概要「要注意イベント」下限スコア（一般設定 0〜100）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 概要タブの「要注意イベント（上位）」一覧を、`notable_score` の下限で絞り込む。下限は **設定 → 一般** で **0〜100** の整数として指定し、ブラウザに保存する。

**Architecture:** 一覧データは [`dashboard.py`](src/vcenter_event_assistant/api/routes/dashboard.py) の `top_q` で取得する。クエリパラメータ `top_notable_min_score`（0〜100、整数）を受け取り、`EventRecord.notable_score >= top_notable_min_score` を WHERE に追加する（0 のときは実質「下限なし」＝非負スコアはすべて通過）。フロントは一般設定と概要の両方で同じ値を参照するため、**TimeZone / Theme と同様に** localStorage + React Context（Provider）で保持し、`SummaryPanel` の `load` で `/api/dashboard/summary?top_notable_min_score=N` を呼ぶ。サーバー側の `.env` だけの設定では UI 要件を満たせないため、**DB マイグレーションは行わない**（単一ブラウザ単位の設定）。

**Tech Stack:** FastAPI `Query`, SQLAlchemy, pytest, React, Zod（既存 `apiGet`）、localStorage。

---

## ファイル構成

| ファイル | 責務 |
|---------|------|
| [`src/vcenter_event_assistant/api/routes/dashboard.py`](src/vcenter_event_assistant/api/routes/dashboard.py) | `dashboard_summary` に `top_notable_min_score` クエリを追加し `top_q` に反映。 |
| [`tests/test_dashboard_summary.py`](tests/test_dashboard_summary.py) | クエリパラメータと WHERE の振る舞いのテスト。 |
| 新規 `frontend/src/preferences/summaryTopNotableMinScoreStorage.ts` | キー定数、`read` / `write`、0〜100 にクランプ。 |
| 新規 `frontend/src/preferences/SummaryTopNotableMinScoreProvider.tsx`（または `GeneralPreferences` に統合） | `useState` 初期値は storage、`set` で storage 更新。`TimeZoneProvider` と同パターン。 |
| [`frontend/src/panels/settings/GeneralSettingsPanel.tsx`](frontend/src/panels/settings/GeneralSettingsPanel.tsx) | `type="number"`、`min={0}` `max={100}`、`step={1}`、説明文。 |
| [`frontend/src/panels/summary/SummaryPanel.tsx`](frontend/src/panels/summary/SummaryPanel.tsx) | Context から下限を読み、fetch URL にクエリを付与。`load` / `useCallback` / `useEffect` の依存に下限を含める。 |
| [`frontend/src/App.tsx`](frontend/src/App.tsx) | Provider を `TimeZoneProvider` 内（または外側で問題なければ隣接）でラップ。 |

**デフォルト値:** 未設定時は **1**（スコア 0 を一覧から除外しやすい）。`0` は「下限なし」に相当。

---

## タスク分解

### Task 1: バックエンド — クエリパラメータとフィルタ

**Files:**
- Modify: [`src/vcenter_event_assistant/api/routes/dashboard.py`](src/vcenter_event_assistant/api/routes/dashboard.py)
- Test: [`tests/test_dashboard_summary.py`](tests/test_dashboard_summary.py)

- [ ] **Step 1: 失敗するテスト**

  24h 以内に `notable_score` が **50 と 0** のイベントを投入。`GET /api/dashboard/summary?top_notable_min_score=1` の `top_notable_events` にスコア 0 が **含まれない** こと。`top_notable_min_score=0` では **両方取得可能**（件数・順序は既存の `order_by` に従う）ことを確認。

- [ ] **Step 2:** `pytest` で失敗を確認。

- [ ] **Step 3:** `from fastapi import Query` 等で `top_notable_min_score: Annotated[int, Query(ge=0, le=100)] = 1` を `dashboard_summary` に追加し、`top_q` の `.where(..., EventRecord.notable_score >= top_notable_min_score)` を付与。

- [ ] **Step 4:** `pytest tests/test_dashboard_summary.py -v` で PASS。

- [ ] **Step 5:** コミット（conventional commits）。

---

### Task 2: フロント — 保存・Provider・一般・概要

**Files:**
- Create: `frontend/src/preferences/summaryTopNotableMinScoreStorage.ts`
- Create: `frontend/src/preferences/SummaryTopNotableMinScoreProvider.tsx` + `useSummaryTopNotableMinScore.ts`（または `context` 同梱）
- Modify: [`frontend/src/App.tsx`](frontend/src/App.tsx)
- Modify: [`frontend/src/panels/settings/GeneralSettingsPanel.tsx`](frontend/src/panels/settings/GeneralSettingsPanel.tsx)
- Modify: [`frontend/src/panels/summary/SummaryPanel.tsx`](frontend/src/panels/summary/SummaryPanel.tsx)

- [ ] **Step 1:** storage モジュール（`read` は数値でパース失敗時はデフォルト 1、`write` はクランプ 0〜100）。

- [ ] **Step 2:** Provider で初期化し、一般タブの `<input type="number" min={0} max={100} />` を双方向バインド。

- [ ] **Step 3:** `SummaryPanel` で `apiGet(\`/api/dashboard/summary?top_notable_min_score=${n}\`)`（`URLSearchParams` 利用でも可）。

- [ ] **Step 4:** フロント単体テスト（storage のクランプ・デフォルト）を [`frontend/src/datetime/timeZoneStorage.test.ts`](frontend/src/datetime/timeZoneStorage.test.ts) に倣って追加するか、新規 `*.test.ts`。

- [ ] **Step 5:** `npm test` / `vitest` で確認後コミット。

---

### Task 3: E2E（任意・推奨）

- [ ] [`frontend/e2e/app-flows.spec.ts`](frontend/e2e/app-flows.spec.ts) 等で、一般設定変更後に概要 API が期待クエリで呼ばれる、または表示が更新されることを最低限確認できるなら追加。

---

## 実行引き渡し

実装完了後は @superpowers:verification-before-completion に従い、`pytest` とフロントテストを実行してから完了宣言する。

**実行オプション:** 計画承認後、(1) サブエージェント駆動（推奨）(2) executing-plans によるインライン実行。
