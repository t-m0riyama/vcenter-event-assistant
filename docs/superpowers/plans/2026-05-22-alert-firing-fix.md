# アラート定期発火の修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** メトリクス閾値アラートが収集データと一致する `metric_key` で評価され、通知履歴に firing が記録される。あわせて `evaluate_alerts` 実行時の観測性を上げ、運用ドキュメントに確認手順を追記する。

**Architecture:** UI の既定値と入力補助を [`KNOWN_METRIC_KEYS`](frontend/src/metrics/knownMetricKeys.ts) に合わせる。バックエンドは [`AlertEvaluator`](src/vcenter_event_assistant/services/alert_eval.py) の評価結果を要約して INFO ログ出力する（ルール数・firing/resolution 件数）。既存の評価ロジックは変えず、キー不一致で黙ってスキップされていた運用バグを塞ぐ。

**Tech Stack:** Python 3.12+ (pytest, caplog), React 19, Vitest, Testing Library, FastAPI APScheduler

---

## Git / ブランチ方針

- **`main` 上での直接実装・直接コミットは行わない**（ユーザーが **`main` でよい**と明示した場合のみ例外）。
- 作業は **feature ブランチ**、または **`git worktree` による隔離ワークツリー**上で行う。
- **コード変更・コミットに入る前**に、読み取り専用のシェルで少なくとも次を実行し、作業報告の冒頭で短文共有する。
  - `git branch --show-current`
  - `git rev-parse --show-toplevel`
  - 可能なら `pwd`
- **実装開始（Task 1 のコード編集前）**は Superpowers の **`using-git-worktrees`** に従い隔離ワークツリーを用意する。
  - 推奨: ブランチ `feature/alert-firing-fix`、ワークツリー `.worktrees/feature-alert-firing-fix/`
- **`main` へのマージ・`git push origin main`** はユーザーの明示がない限りエージェントから実行しない。

詳細: [docs/snippets/git-branch-policy-for-plans.md](../snippets/git-branch-policy-for-plans.md)

---

## 背景（なぜ発火しないように見えるか）

- `evaluate_alerts` の **executed successfully** は例外なしのみ。ルール 0 件・閾値未満・`metric_key` 不一致では何も起きない。
- UI 新規ルールの既定 `metric_key` が `cpu.usage.average` だが、収集キーは `host.cpu.usage_pct`（[`AlertRulesPanel.tsx`](frontend/src/panels/settings/AlertRulesPanel.tsx) L53 vs [`knownMetricKeys.ts`](frontend/src/metrics/knownMetricKeys.ts)）。
- 通知履歴・メールは [`_notify`](src/vcenter_event_assistant/services/alert_eval.py) 到達時のみ。メールは SMTP 未設定でも履歴は残る。

---

## ファイル構成

| ファイル | 変更 |
|----------|------|
| **Create** [`frontend/src/panels/settings/alertRuleDefaults.ts`](frontend/src/panels/settings/alertRuleDefaults.ts) | 既定メトリクスキー定数（テスト可能） |
| **Modify** [`frontend/src/panels/settings/AlertRulesPanel.tsx`](frontend/src/panels/settings/AlertRulesPanel.tsx) | 定数利用・datalist・placeholder |
| **Create** [`frontend/src/panels/settings/AlertRulesPanel.test.tsx`](frontend/src/panels/settings/AlertRulesPanel.test.tsx) | 新規 POST payload テスト |
| **Modify** [`src/vcenter_event_assistant/services/alert_eval.py`](src/vcenter_event_assistant/services/alert_eval.py) | 評価サマリ・DEBUG ログ |
| **Modify** [`tests/test_alert_eval_metrics.py`](tests/test_alert_eval_metrics.py) | キー不一致/一致の回帰 |
| **Create** [`tests/test_alert_eval_logging.py`](tests/test_alert_eval_logging.py) | caplog でサマリログ |
| **Modify** [`docs/backend.md`](docs/backend.md) | アラート運用・トラブルシュート節 |

---

### Task 0: ワークツリー準備

- [ ] **Step 1:** `using-git-worktrees` で `.worktrees/feature-alert-firing-fix/` + `feature/alert-firing-fix` を作成
- [ ] **Step 2:** ベースライン

```bash
cd .worktrees/feature-alert-firing-fix
uv run pytest tests/test_alert_eval_metrics.py tests/test_alert_eval_events.py -q
npm run --prefix frontend test -- src/api/alertRulesFile.test.ts
```

Expected: PASS

---

### Task 1: 既定メトリクスキー定数（フロント）

**Files:**
- Create: `frontend/src/panels/settings/alertRuleDefaults.ts`
- Test: `frontend/src/panels/settings/alertRuleDefaults.test.ts`

- [ ] **Step 1: Write the failing test**

`frontend/src/panels/settings/alertRuleDefaults.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'
import { DEFAULT_ALERT_METRIC_KEY } from './alertRuleDefaults'

describe('alertRuleDefaults', () => {
  it('DEFAULT_ALERT_METRIC_KEY matches collector CPU key', () => {
    expect(DEFAULT_ALERT_METRIC_KEY).toBe('host.cpu.usage_pct')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm run --prefix frontend test -- src/panels/settings/alertRuleDefaults.test.ts
```

Expected: FAIL — module not found

- [ ] **Step 3: Write minimal implementation**

`frontend/src/panels/settings/alertRuleDefaults.ts`:

```typescript
/** 収集パイプラインが DB に保存する CPU 利用率キー（knownMetricKeys と一致）。 */
export const DEFAULT_ALERT_METRIC_KEY = 'host.cpu.usage_pct' as const
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm run --prefix frontend test -- src/panels/settings/alertRuleDefaults.test.ts
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/panels/settings/alertRuleDefaults.ts frontend/src/panels/settings/alertRuleDefaults.test.ts
git commit -m "fix(frontend): align default alert metric key with collector

メトリクス閾値ルールの既定 metric_key を host.cpu.usage_pct に固定する。
"
```

---

### Task 2: AlertRulesPanel の既定値と datalist（TDD）

**Files:**
- Modify: `frontend/src/panels/settings/AlertRulesPanel.tsx`
- Test: `frontend/src/panels/settings/AlertRulesPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/panels/settings/AlertRulesPanel.test.tsx`（[`VCentersPanel.test.tsx`](frontend/src/panels/settings/VCentersPanel.test.tsx) と同パターン）:

```typescript
/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AlertRulesPanel } from './AlertRulesPanel'

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('AlertRulesPanel metric_threshold create', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('新規メトリクスルールの POST に host.cpu.usage_pct が含まれる', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          id: 1,
          name: 'CPU rule',
          rule_type: 'metric_threshold',
          is_enabled: true,
          alert_level: 'warning',
          config: { metric_key: 'host.cpu.usage_pct', threshold: 90 },
        }, 201),
      )
      .mockResolvedValueOnce(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    render(<AlertRulesPanel onError={vi.fn()} />)

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/alerts/rules', expect.any(Object))
    })

    fireEvent.click(screen.getByRole('button', { name: '新規追加' }))
    fireEvent.change(screen.getByLabelText('ルール名'), { target: { value: 'CPU rule' } })
    fireEvent.change(screen.getByLabelText('タイプ'), { target: { value: 'metric_threshold' } })

    const metricInput = screen.getByLabelText('メトリクスキー') as HTMLInputElement
    expect(metricInput.value).toBe('host.cpu.usage_pct')

    fireEvent.change(screen.getByLabelText('閾値'), { target: { value: '90' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        (c) => c[0] === '/api/alerts/rules' && (c[1] as RequestInit)?.method === 'POST',
      )
      expect(postCall).toBeDefined()
      const body = JSON.parse(String((postCall![1] as RequestInit).body))
      expect(body.config.metric_key).toBe('host.cpu.usage_pct')
    })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm run --prefix frontend test -- src/panels/settings/AlertRulesPanel.test.tsx
```

Expected: FAIL — `metricInput.value` is `cpu.usage.average`

- [ ] **Step 3: Write minimal implementation**

`AlertRulesPanel.tsx` の変更:

```typescript
import { DEFAULT_ALERT_METRIC_KEY } from './alertRuleDefaults'
import { KNOWN_METRIC_KEYS } from '../../metrics/knownMetricKeys'

// useState 初期値
const [newMetricKey, setNewMetricKey] = useState(DEFAULT_ALERT_METRIC_KEY)

// 新規フォーム input（L346-355 付近）
<input
  type="text"
  list="alert-metric-key-options"
  value={newMetricKey}
  onChange={(e) => setNewMetricKey(e.target.value)}
  placeholder={DEFAULT_ALERT_METRIC_KEY}
/>
<datalist id="alert-metric-key-options">
  {KNOWN_METRIC_KEYS.map((key) => (
    <option key={key} value={key} />
  ))}
</datalist>

// 編集行 input にも list="alert-metric-key-options" を付与
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm run --prefix frontend test -- src/panels/settings/AlertRulesPanel.test.tsx
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/panels/settings/AlertRulesPanel.tsx frontend/src/panels/settings/AlertRulesPanel.test.tsx
git commit -m "fix(frontend): suggest collected metric keys in alert rules UI

既定 metric_key と datalist で収集キーと一致しやすくする。
"
```

---

### Task 3: 評価サマリのログ（バックエンド TDD）

**Files:**
- Modify: `src/vcenter_event_assistant/services/alert_eval.py`
- Create: `tests/test_alert_eval_logging.py`

- [ ] **Step 1: Write the failing test**

`tests/test_alert_eval_logging.py`:

```python
import logging

import pytest
from vcenter_event_assistant.services.alert_eval import AlertEvaluator


@pytest.mark.asyncio
async def test_evaluate_all_logs_summary_with_zero_rules(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="vcenter_event_assistant.services.alert_eval")
    evaluator = AlertEvaluator()
    await evaluator.evaluate_all()
    messages = [r.message for r in caplog.records if r.name == "vcenter_event_assistant.services.alert_eval"]
    assert any("alert evaluation complete" in m and "rules_enabled=0" in m for m in messages)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_alert_eval_logging.py::test_evaluate_all_logs_summary_with_zero_rules -v
```

Expected: FAIL — no matching log line

- [ ] **Step 3: Write minimal implementation**

`alert_eval.py` に dataclass とカウンタ（モジュール内）:

```python
from dataclasses import dataclass

@dataclass
class AlertEvalSummary:
    rules_enabled: int = 0
    firings: int = 0
    resolutions: int = 0

class AlertEvaluator:
    def __init__(self) -> None:
        ...
        self._last_summary = AlertEvalSummary()

    async def evaluate_all(self) -> AlertEvalSummary:
        summary = AlertEvalSummary()
        async with session_scope() as session:
            res = await session.execute(select(AlertRule).where(AlertRule.is_enabled.is_(True)))
            rules = res.scalars().all()
        summary.rules_enabled = len(rules)
        for rule in rules:
            try:
                if rule.rule_type == "event_score":
                    f, r = await self._evaluate_event_score(rule)
                elif rule.rule_type == "metric_threshold":
                    f, r = await self._evaluate_metric_threshold(rule)
                else:
                    f, r = 0, 0
                summary.firings += f
                summary.resolutions += r
            except Exception as e:
                logger.error(...)
        logger.info(
            "alert evaluation complete rules_enabled=%s firings=%s resolutions=%s",
            summary.rules_enabled,
            summary.firings,
            summary.resolutions,
        )
        self._last_summary = summary
        return summary
```

`_evaluate_event_score` / `_evaluate_metric_threshold` は **`_notify` 呼び出し時に** `(1, 0)` firing または `(0, 1)` resolved を返すよう末尾でカウント（既存ロジックの各 `_notify` 直前に `return` パターンを整理。重複 `_notify` なしのパスは `0, 0`）。

`_evaluate_metric_threshold` で `latest_samples` が空のとき:

```python
if not latest_samples:
    logger.debug(
        "metric_threshold rule=%s metric_key=%s: no samples in DB",
        rule.name,
        metric_key,
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_alert_eval_logging.py tests/test_alert_eval_metrics.py tests/test_alert_eval_events.py -v
```

Expected: PASS（既存テストは `_notify` を patch しているためカウンタ 0 のままでも可。firing テスト 1 件で `firings>=1` を assert するテストを追加してもよい）

追加テスト（同ファイル）:

```python
@pytest.mark.asyncio
async def test_evaluate_metric_firing_increments_summary_count(
    caplog: pytest.LogCaptureFixture,
    # reuse fixture pattern from test_alert_eval_metrics
):
    ...
    caplog.set_level(logging.INFO, ...)
    with patch.object(evaluator.email_channel, "notify", new_callable=AsyncMock):
        await evaluator.evaluate_all()
    assert any("firings=1" in r.message for r in caplog.records)
```

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/alert_eval.py tests/test_alert_eval_logging.py
git commit -m "feat(alerts): log alert evaluation summary each run

evaluate_alerts 後に rules_enabled/firings/resolutions を INFO で出す。
"
```

---

### Task 4: metric_key 不一致の回帰テスト（TDD）

**Files:**
- Modify: `tests/test_alert_eval_metrics.py`

- [ ] **Step 1: Write the failing test**

`tests/test_alert_eval_metrics.py` に追加:

```python
@pytest.mark.asyncio
async def test_metric_threshold_does_not_fire_when_metric_key_mismatches_collector():
    async with session_scope() as session:
        vc = VCenter(name="vc_key", host="vc_key", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Wrong key",
            rule_type="metric_threshold",
            is_enabled=True,
            config={"metric_key": "cpu.usage.average", "threshold": 90.0},
        )
        session.add(rule)
        session.add(
            MetricSample(
                vcenter_id=vc.id,
                sampled_at=datetime.now(timezone.utc),
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="ESXi-1",
                metric_key="host.cpu.usage_pct",
                value=95.0,
            )
        )
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert not mock_notify.called


@pytest.mark.asyncio
async def test_metric_threshold_fires_when_metric_key_matches_collector():
    async with session_scope() as session:
        vc = VCenter(name="vc_ok", host="vc_ok", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Right key",
            rule_type="metric_threshold",
            is_enabled=True,
            config={"metric_key": "host.cpu.usage_pct", "threshold": 90.0},
        )
        session.add(rule)
        session.add(
            MetricSample(
                vcenter_id=vc.id,
                sampled_at=datetime.now(timezone.utc),
                entity_type="HostSystem",
                entity_moid="host-1",
                entity_name="ESXi-1",
                metric_key="host.cpu.usage_pct",
                value=95.0,
            )
        )
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_alert_eval_metrics.py -v
```

Expected: 既存 `cpu.usage` テストはそのまま PASS。新規 2 件 PASS（実装済み evaluator の現状で mismatch は既に not called、match は called — RED は不要なら Step 2 で即 PASS でもよい。TDD 精神では mismatch テストを先に書き、意図を固定する）。

- [ ] **Step 3: Commit**

```bash
git add tests/test_alert_eval_metrics.py
git commit -m "test(alerts): document metric_key must match stored samples

収集キー host.cpu.usage_pct と UI 旧既定の不一致を回帰で固定する。
"
```

---

### Task 5: ドキュメント

**Files:**
- Modify: `docs/backend.md`（§2.4 直後に小節追加）

- [ ] **Step 1:** 次の内容を追記（日本語）:

  - 定期評価は `alert_eval_interval_seconds`（既定 60s）
  - **有効な AlertRule が 1 件以上必要**
  - `metric_threshold` の `metric_key` は `GET /api/metrics/keys` またはグラフタブのキーと **完全一致**
  - 発火確認は **通知履歴**（`GET /api/alerts/history`）。メールは `SMTP_HOST` + `ALERT_EMAIL_TO` 設定時のみ
  - ログの `alert evaluation complete rules_enabled=... firings=...` の見方
  - 既存ルールが `cpu.usage.average` のままなら UI で `host.cpu.usage_pct` に修正

- [ ] **Step 2: Commit**

```bash
git add docs/backend.md
git commit -m "docs: add alert rule metric_key troubleshooting

定期 evaluate_alerts が静かに成功する場合の確認手順を追記する。
"
```

---

### Task 6: 仕上げ

- [ ] **Step 1: フロント全体**

```bash
npm run --prefix frontend test
npm run --prefix frontend run build
```

- [ ] **Step 2: バックエンド関連**

```bash
uv run pytest tests/test_alert_eval_metrics.py tests/test_alert_eval_events.py tests/test_alert_eval_logging.py -v
uv run ruff check src/vcenter_event_assistant/services/alert_eval.py
```

- [ ] **Step 3: 手動確認チェックリスト**

  - 設定で新規メトリクスルール作成 → 既定キーが `host.cpu.usage_pct`
  - 閾値を下げる or 高負荷ホストで `poll_perf` 後 1 分以内に通知履歴に firing
  - ログに `alert evaluation complete rules_enabled=1 firings=1`（初回のみ）

---

## Spec セルフレビュー

| 要件 | Task |
|------|------|
| UI 既定 metric_key 修正 | 1, 2 |
| datalist 補助 | 2 |
| 評価サマリ INFO ログ | 3 |
| metric_key 回帰テスト | 4 |
| ドキュメント | 5 |

プレースホルダー: なし。

---

## ユーザー向け（マージ後の即時対処・コード不要）

既に作成済みルールの `metric_key` が `cpu.usage.average` の場合は、設定 → アラートで **`host.cpu.usage_pct`** に編集し、ルールを有効のまま 1〜2 分待つ。通知履歴に行が出れば評価は動作している（メールは SMTP 設定別）。
