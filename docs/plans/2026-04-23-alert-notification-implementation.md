# アラート通知機能 実装計画

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** イベントのスコアやメトリクスの閾値に基づき、状態遷移（発火/回復）を管理してメール通知する機能を追加する。

**Architecture:** 通知チャネルを抽象化し、評価エンジンがルールをDBから読み込んで収集済みデータと比較、状態遷移が発生した時のみ通知を行う。Jinja2 テンプレートにより本文をカスタマイズ可能にする。

**Tech Stack:** Python, FastAPI, SQLAlchemy, Alembic, Jinja2, React (Frontend), Vitest (Frontend Test)

---

### Task 1: データベースモデルの作成とマイグレーション

**Files:**
- Modify: `src/vcenter_event_assistant/db/models.py`
- Create: `alembic/versions/YYYY_MM_DD_add_alert_tables.py` (自動生成)

**Step 1: `models.py` に `AlertRule`, `AlertState`, `AlertHistory` を追加する**

**Step 2: マイグレーションファイルを生成・適用する**
- Run: `uv run alembic revision --autogenerate -m "add alert tables"`
- Run: `uv run alembic upgrade head`

**Step 3: テストでテーブルの存在を確認する**
- Create: `tests/test_alert_models.py`
- Run: `uv run pytest tests/test_alert_models.py`

**Step 4: Commit**
```bash
git add src/vcenter_event_assistant/db/models.py alembic/versions/ tests/test_alert_models.py
git commit -m "feat(db): add alert notification tables"
```

---

### Task 2: 設定と環境変数の追加

**Files:**
- Modify: `src/vcenter_event_assistant/settings.py`

**Step 1: SMTP 設定とアラート評価間隔を `Settings` クラスに追加する**

**Step 2: テストでデフォルト値を確認する**
- Create: `tests/test_alert_settings.py`
- Run: `uv run pytest tests/test_alert_settings.py`

**Step 3: Commit**
```bash
git add src/vcenter_event_assistant/settings.py tests/test_alert_settings.py
git commit -m "feat(config): add SMTP and alert settings"
```

---

### Task 3: 通知レンダリングとメール送信サービス (TDD)

**Files:**
- Create: `src/vcenter_event_assistant/services/notification/base.py`
- Create: `src/vcenter_event_assistant/services/notification/email_channel.py`
- Create: `src/vcenter_event_assistant/services/notification/renderer.py`
- Create: `src/vcenter_event_assistant/templates/alert_firing.txt.j2`
- Create: `src/vcenter_event_assistant/templates/alert_resolved.txt.j2`

**Step 1: 失敗するテストを書く（レンダリング）**
- Create: `tests/test_alert_renderer.py`
- Run: `uv run pytest tests/test_alert_renderer.py` (FAIL)

**Step 2: テンプレートとレンダリングロジックを実装する**

**Step 3: テストをパスさせる**

**Step 4: メール送信サービスのモックテストを書く**
- Create: `tests/test_email_channel.py`

**Step 5: Commit**
```bash
git add src/vcenter_event_assistant/services/notification/ src/vcenter_event_assistant/templates/ tests/test_alert_renderer.py tests/test_email_channel.py
git commit -m "feat(services): add notification rendering and email channel"
```

---

### Task 4: アラート評価エンジンの実装 (TDD)

**Files:**
- Create: `src/vcenter_event_assistant/services/alert_eval.py`

**Step 1: イベントスコア閾値の評価テストを書く**
- Create: `tests/test_alert_eval_events.py`

**Step 2: 評価エンジンの骨組みを実装する**

**Step 3: メトリクス閾値の評価テストを書く**
- Create: `tests/test_alert_eval_metrics.py`

**Step 4: 実装を完成させ、状態遷移（firing -> resolved）を処理できるようにする**

**Step 5: Commit**
```bash
git add src/vcenter_event_assistant/services/alert_eval.py tests/test_alert_eval_events.py tests/test_alert_eval_metrics.py
git commit -m "feat(services): add alert evaluation engine"
```

---

### Task 5: API エンドポイントの実装 (TDD)

**Files:**
- Create: `src/vcenter_event_assistant/api/routes/alerts.py`
- Modify: `src/vcenter_event_assistant/api/schemas.py`
- Modify: `src/vcenter_event_assistant/main.py`

**Step 1: スキーマの定義を追加する**

**Step 2: API 統合テストを書く（CRUD）**
- Create: `tests/test_alerts_api.py`

**Step 3: ルートを実装し、`main.py` に登録する**

**Step 4: Commit**
```bash
git add src/vcenter_event_assistant/api/ src/vcenter_event_assistant/main.py tests/test_alerts_api.py
git commit -m "feat(api): add alert rules and history endpoints"
```

---

### Task 6: スケジューラへの統合

**Files:**
- Modify: `src/vcenter_event_assistant/jobs/scheduler.py`

**Step 1: `evaluate_alerts` ジョブを登録する**

**Step 2: Commit**
```bash
git add src/vcenter_event_assistant/jobs/scheduler.py
git commit -m "feat(jobs): integrate alert evaluation to scheduler"
```

---

### Task 7: フロントエンド - 通知履歴タブの実装

**Files:**
- Create: `frontend/src/panels/alerts/AlertHistoryPanel.tsx`
- Modify: `frontend/src/App.tsx` (タブ追加)

**Step 1: 通知履歴一覧を表示するパネルを作成する**

**Step 2: メインタブに「通知履歴」を追加する**

**Step 3: Commit**
```bash
git add frontend/src/
git commit -m "feat(frontend): add notification history main tab"
```

---

### Task 8: フロントエンド - 設定 > Alerts タブの実装

**Files:**
- Create: `frontend/src/panels/settings/AlertRulesPanel.tsx`
- Modify: `frontend/src/panels/settings/SettingsPanel.tsx` (サブタブ追加)

**Step 1: アラートルールの管理UIを作成する**

**Step 2: 設定パネルに「Alerts」タブを追加する**

**Step 3: Commit**
```bash
git add frontend/src/
git commit -m "feat(frontend): add alert rules management in settings"
```
