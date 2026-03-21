# Host/Datastore Disk & Network Perf Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ESXi ホストについて、ネットワークの **エラー/ドロップ** に加え **利用状況（スループット等）**、および **ディスク利用（ホスト I/O・データストア容量）** を vSphere API 経由で取得し、既存の `metric_samples` に蓄積する。

**Architecture:** 現状の `host.cpu.usage_pct` / `host.mem.usage_pct` は `HostSystem.summary.quickStats` のみ（`src/vcenter_event_assistant/collectors/perf.py`）。追加メトリクスは次の二系統に分ける。(1) **PerformanceManager**（`QueryAvailablePerfMetric` + `QueryPerf`、リアルタイム間隔）で `HostSystem` の `net` / `disk` グループからレート系・利用率系を取得。(2) **Datastore** については、まず **`vim.Datastore.summary` の容量・空き** から使用率％を算出する（追加の QueryPerf が不要であれば YAGNI）。カウンタ名・単位は vCenter バージョンで差があるため、**解決できないものはスキップ**し、取得できた系列だけ保存する。累積カウンタ（errors/drops）はキー名に `_total` を付与し、レート系は単位をキーに含める（例: `_kbps`）。

**Tech Stack:** Python 3.12 + `pyVmomi`、FastAPI / SQLAlchemy（既存）、pytest。

---

## スコープ整理

| 区分 | 内容 |
|------|------|
| ネット（エラー系） | 既存方針どおり errors / drops（多くは summation・累積） |
| ネット（利用状況） | 送受スループット、（利用可能なら）集約利用率など **errors/drops 以外** |
| ディスク（ホスト） | I/O レート、（利用可能なら）`disk.usage` 等の利用率 |
| ディスク（データストア） | 使用率％（容量に対する使用割合）を優先。必要なら個別 DS の使用容量 |

---

## 前提・メトリクスキー（確定案）

### A. ネットワーク（HostSystem）— エラー / ドロップ（累積）

| `metric_key` | 意味 | 典型カウンタ（グループ `net`） |
|--------------|------|-------------------------------|
| `host.net.errors_rx_total` | 受信エラー累計 | `errorsRx`（summation） |
| `host.net.errors_tx_total` | 送信エラー累計 | `errorsTx`（summation） |
| `host.net.dropped_rx_total` | 受信ドロップ累計 | `droppedRx`（summation） |
| `host.net.dropped_tx_total` | 送信ドロップ累計 | `droppedTx`（summation） |

### B. ネットワーク（HostSystem）— 利用状況（エラー以外）

| `metric_key` | 意味 | 典型カウンタ（グループ `net`） | 備考 |
|--------------|------|-------------------------------|------|
| `host.net.bytes_rx_kbps` | 受信スループット | `bytesRx`（average、KB/s） | vSphere の単位は KB/s 想定。保存値は float。 |
| `host.net.bytes_tx_kbps` | 送信スループット | `bytesTx`（average） | 同上 |
| `host.net.usage_kbps` | 集約ネット利用（取得可能な場合） | `usage`（average） | 環境により **存在しない** 場合あり → スキップ可 |

**注意:** NIC 別系列が返る場合は **ホスト全体として合算**（レートの合算は解釈として妥当）。

### C. ディスク（HostSystem）

| `metric_key` | 意味 | 典型カウンタ（グループ `disk`） |
|--------------|------|--------------------------------|
| `host.disk.usage_pct` | ディスク利用率（％） | `usage`（average）※環境により定義が異なる可能性 |
| `host.disk.read_kbps` | 読み取りレート | `read`（average） |
| `host.disk.write_kbps` | 書き込みレート | `write`（average） |

**注意:** `disk.usage` が無い / 意味が薄い場合は **read/write のみ**でも可（YAGNI）。

### D. データストア（Datastore、`entity_type`: `Datastore`）

| `metric_key` | 意味 | 取得方法 |
|--------------|------|----------|
| `datastore.space.used_pct` | 使用容量 ÷ 総容量（0〜100） | `summary.capacity` と `summary.freeSpace` から算出 |
| `datastore.space.used_bytes` | 使用バイト（任意） | 上記から計算。不要なら省略可 |

`entity_moid` / `entity_name` は Datastore の `_moId` / `name`。

---

## ファイル構成（変更・新規）

| ファイル | 役割 |
|----------|------|
| `src/vcenter_event_assistant/collectors/perf.py` | ホスト/Datastore を列挙し、CPU/メモリ・各種サンプルを結合して返す |
| `src/vcenter_event_assistant/collectors/host_perf_counters.py`（新規・名前は実装で可） | `PerformanceManager` により HostSystem の `net` / `disk` 向け QueryPerf をまとめ、行 dict に変換（errors/drops + utilization + disk IO） |
| `src/vcenter_event_assistant/collectors/datastore_metrics.py`（新規） | Datastore の `summary` から使用率行を生成（Perf 不要ならここだけ） |
| `src/vcenter_event_assistant/services/ingestion.py` | 変更なし（行が増えるだけ） |
| `tests/test_host_perf_counters.py`（新規） | QueryPerf / summary のパースをモックで検証 |
| `tests/test_datastore_metrics.py`（新規） | Datastore 使用率の純関数テスト（容量 0 除算ガード含む） |
| `tests/test_metrics_api.py` | 任意: 新 `metric_key` を 1 件ずつ追加して `/api/metrics/keys` を確認 |
| `src/vcenter_event_assistant/api/routes/dashboard.py` + スキーマ + `SummaryPanel.tsx` | **オプション:** 高ネット利用率・高 DS 使用率など |

---

### Task 1: Host 向け PerformanceManager（エラー/ドロップ + ネット・ディスク利用）

**Files:**
- Create: `src/vcenter_event_assistant/collectors/host_perf_counters.py`
- Create: `tests/test_host_perf_counters.py`

- [ ] **Step 1: Write the failing test**

モック `QueryPerf` 戻り値に、`host.net.dropped_rx_total` と `host.net.bytes_rx_kbps` と `host.disk.read_kbps` が同時に解釈できる最小ケースを用意し、公開関数（例: `collect_host_perf_metric_rows(si, host) -> list[dict]`）の `metric_key` 集合を検証する。

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/test_host_perf_counters.py -v`

- [ ] **Step 3: Implement**

- `QueryAvailablePerfMetric` で `net` / `disk` の `PerfMetricId` を、上表の **論理名 → metric_key** マップに従って解決する。
- **A 系（summation）** と **B/C 系（average）** で rollup が異なるため、`PerfCounterInfo.rollupType` を確認して選別する。
- 複数 `instance` は合算または代表インスタンス選択（実装コメントで理由を 1 行）。
- 例外は握りつぶさず、**そのホスト分の Perf 行だけ**空リスト＋`logger.warning`（計画どおり）。

- [ ] **Step 4: Run test — expect PASS**

Run: `uv run pytest tests/test_host_perf_counters.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/collectors/host_perf_counters.py tests/test_host_perf_counters.py
git commit -m "feat(collectors): add host net/disk perf metrics via PerformanceManager"
```

---

### Task 2: Datastore 使用率（summary ベース）

**Files:**
- Create: `src/vcenter_event_assistant/collectors/datastore_metrics.py`
- Create: `tests/test_datastore_metrics.py`

- [ ] **Step 1: Write the failing test**

`capacity` / `freeSpace` を与えたモック Datastore から `datastore.space.used_pct` が期待通りになること。`capacity == 0` のときは行を出さないか `0` 固定など、**ガード方針をテストで固定**する。

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest tests/test_datastore_metrics.py -v`

- [ ] **Step 3: Implement**

`CreateContainerView(..., [vim.Datastore], True)` で列挙し、各 DS について 1 行以上生成（`entity_type="Datastore"`）。

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/collectors/datastore_metrics.py tests/test_datastore_metrics.py
git commit -m "feat(collectors): add datastore space usage percent from summary"
```

---

### Task 3: `sample_hosts_blocking` への統合

**Files:**
- Modify: `src/vcenter_event_assistant/collectors/perf.py`

- [ ] **Step 1: Write the failing test**

`unittest.mock.patch` で `connect_vcenter` と collector を差し替え、1 ホストあたり CPU/メモリ + 新 Host 行が結合されることを検証（`tests/test_host_perf_counters.py` に追加しても可）。

- [ ] **Step 2: Implement**

各ホスト: `_host_metrics(h)` に `collect_host_perf_metric_rows(si, h)` を `extend`。失敗時は CPU/メモリは維持。

- [ ] **Step 3: Add Datastore pass**

同じ `sample_hosts_blocking` の末尾、または別関数 `sample_datastores_blocking` を呼び出し、ingestion が 1 ループで取り込める形に統一（**1 vCenter 接続で** host + datastore を返すなら、`perf.py` 内で順に `rows.extend(...)`）。

- [ ] **Step 4: Run** `uv run pytest -q`

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/collectors/perf.py tests/test_host_perf_counters.py
git commit -m "feat(collectors): wire host perf and datastore rows into sampling"
```

---

### Task 4: 回帰（API・全テスト）

- [ ] **Step 1:** `uv run pytest -q`
- [ ] **Step 2:** `uv run ruff check src tests`

---

### Task 5: `GET /api/metrics/keys` の拡張確認（任意）

**Files:**
- Modify: `tests/test_metrics_api.py`

- [ ] `host.net.bytes_rx_kbps` と `datastore.space.used_pct` のサンプルを挿入し、キー一覧にソート順で含まれることを確認。

---

### Task 6（オプション）: ダッシュボードサマリー

**方針:** 累積系（errors/drops）は「直近 24h 最大サンプル」は解釈が難しい。レート系・`used_pct` は **直近 24h で値が大きいホスト/DS** のランキング表示が可能。オプションで `high_network_throughput_hosts` / `high_datastore_usage` などを追加。

---

## 手動検証（本番相当 vCenter）

1. `perf_sample_interval_seconds` / `metric_retention_days` を確認。
2. スケジュール 1 回後、`GET /api/metrics/keys` に `host.net.bytes_rx_kbps`, `host.disk.read_kbps`, `datastore.space.used_pct` 等が現れること。
3. メトリクスタブで系列が表示できること（フロントはキー列挙型なら追加実装なし）。

---

## Plan Review Loop

@superpowers:writing-plans — 完成後は `plan-document-reviewer` を別コンテキストで実行。

---

## Execution Handoff

**採用:** **1. Subagent-Driven** — タスクごとに新しいサブエージェントを起動し、タスク間でレビューする。**REQUIRED SUB-SKILL:** `superpowers:subagent-driven-development`。

計画の正本: `docs/superpowers/plans/2026-03-22-host-disk-network-perf-metrics.md`
