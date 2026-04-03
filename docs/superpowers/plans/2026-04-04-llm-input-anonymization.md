# LLM 入力の識別子匿名化（チャット + ダイジェスト）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** vCenter 由来のホスト名・IP・VM/エンティティ名・ユーザー名などを LLM API に送る直前だけトークンに置換し、応答本文（およびダイジェスト要約の結合前テキスト）をサーバ側で逆変換して、保存・表示は実名ベースに保つ。

**Architecture:** 純関数モジュール `llm_anonymization` が「JSON 互換オブジェクトの再帰走査」「任意文字列へのパターン置換（補助）」「同一原文→同一トークン」「逆変換」を担当する。`run_period_chat` と `augment_digest_with_llm` は LLM 呼び出し直前に同じ API を通し、トークン予算調整（`_fit_chat_payload_to_token_budget`）は**匿名化後の dict** を `json.dumps` する既存フローに乗せる。ダイジェストは集約 JSON とテンプレ Markdown を**同一マッピング**で匿名化し、LLM が返した要約だけ逆変換してから `template_markdown` に連結する。機能フラグで無効化可能にし、既存テストを壊さない。

**Tech Stack:** Python 3.12+、Pydantic v2、既存の `Settings`、pytest / pytest-asyncio、フロントはサーバ逆変換のみなら Zod スキーマ変更は最小（任意フィールド追加時のみ）。

**参照:** ブレインストーミング段階の方針は Cursor の計画ファイル `llm入力の記号化検討_48a302a9.plan.md` と整合させる。`docs/superpowers/specs/` への独立 spec は未作成のため、本計画の Goal / Architecture を要件の単一ソースとする。

---

## ファイル構成（新規・変更）

| 責務 | パス |
|------|------|
| 匿名化・逆変換の核 | 新規 `src/vcenter_event_assistant/services/llm_anonymization.py` |
| 単体テスト | 新規 `tests/test_llm_anonymization.py` |
| チャット統合 | 変更 `src/vcenter_event_assistant/services/chat_llm.py` |
| ダイジェスト統合 | 変更 `src/vcenter_event_assistant/services/digest_llm.py` |
| 設定 | 変更 `src/vcenter_event_assistant/settings.py`、`.env.example` |
| チャット結合テスト | 変更 `tests/test_chat_llm.py` |
| ダイジェスト結合テスト | 変更 `tests/test_digest_llm.py` |

---

### Task 1: `LlmAnonymizer` — 同一値の安定トークンと逆変換

**Files:**
- 新規: `src/vcenter_event_assistant/services/llm_anonymization.py`
- 新規: `tests/test_llm_anonymization.py`

**方針:** トークン形式は `__LM_HOST_001__` のように **英大文字カテゴリ + 3 桁連番**（実装でゼロ埋め）。逆引きは `token -> 原文` の dict。長いトークンが短文に誤爆しないよう、逆変換は**トークンを長い順に**置換する。

- [ ] **Step 1: 失敗するテストを書く（RED）**

`tests/test_llm_anonymization.py` に以下を追加する。

```python
from __future__ import annotations

from vcenter_event_assistant.services.llm_anonymization import (
    LlmAnonymizer,
    deanonymize_text,
)


def test_same_value_gets_same_token_per_category() -> None:
    a = LlmAnonymizer()
    t1 = a.token_for("host", "esxi-01.lab.local")
    t2 = a.token_for("host", "esxi-01.lab.local")
    t3 = a.token_for("host", "esxi-02.lab.local")
    assert t1 == t2
    assert t1 != t3
    assert t1.startswith("__LM_HOST_")


def test_deanonymize_restores_order_longest_token_first() -> None:
    a = LlmAnonymizer()
    x = a.token_for("host", "aa")
    y = a.token_for("host", "a")  # 別トークン
    mixed = f"see {y} and {x}"
    assert deanonymize_text(mixed, a.reverse_map) == "see a and aa"
```

- [ ] **Step 2: テストを実行して失敗を確認**

```bash
cd /Users/moriyama/git/vcenter-event-assistant && uv run pytest tests/test_llm_anonymization.py::test_same_value_gets_same_token_per_category -v
```

期待: `ModuleNotFoundError` または `ImportError` / 未定義。

- [ ] **Step 3: 最小実装（GREEN）**

`llm_anonymization.py` に `LlmAnonymizer`（`token_for(category, value: str) -> str`、内部で `(category, value)` ごとに連番）、`reverse_map: dict[str, str]`（トークン→原文）、および `deanonymize_text(text: str, reverse_map: dict[str, str]) -> str` を実装する。

- [ ] **Step 4: テストが通ることを確認**

```bash
uv run pytest tests/test_llm_anonymization.py -v
```

期待: 全て PASS。

- [ ] **Step 5: コミット**

```bash
git add src/vcenter_event_assistant/services/llm_anonymization.py tests/test_llm_anonymization.py
git commit -m "feat(llm): add LlmAnonymizer token registry and deanonymize_text"
```

---

### Task 2: 集約 JSON 風 dict の再帰匿名化

**Files:**
- 変更: `src/vcenter_event_assistant/services/llm_anonymization.py`
- 変更: `tests/test_llm_anonymization.py`

対象キー（値が `str` のときトークン化）の初版:

- `entity_name`
- `message`（イベントメッセージ全文）
- `user_name` / `username`（将来拡張用に列挙に含めてもよい）

`dict` / `list` は再帰。`None`、数値、日時はそのまま。

- [ ] **Step 1: 失敗するテスト（RED）**

```python
def test_anonymize_dict_replaces_entity_name_and_message() -> None:
    from vcenter_event_assistant.services.llm_anonymization import anonymize_json_like

    raw = {
        "top_notable_event_groups": [
            {
                "event_type": "vim.event.Event",
                "entity_name": "VM-DB-01",
                "message": "User root@192.168.1.10 logged in on VM-DB-01",
            }
        ]
    }
    out, rev = anonymize_json_like(raw)
    assert out["top_notable_event_groups"][0]["entity_name"] != "VM-DB-01"
    assert "VM-DB-01" not in str(out)
    assert deanonymize_text(out["top_notable_event_groups"][0]["message"], rev) == raw["top_notable_event_groups"][0]["message"]
```

- [ ] **Step 2: 実行して RED 確認**

```bash
uv run pytest tests/test_llm_anonymization.py::test_anonymize_dict_replaces_entity_name_and_message -v
```

- [ ] **Step 3: 実装（GREEN）** — `anonymize_json_like(obj: Any) -> tuple[Any, dict[str, str]]` を追加。内部で `LlmAnonymizer` を 1 インスタンス使い回す。

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/test_llm_anonymization.py -v`

- [ ] **Step 5: コミット** — `feat(llm): anonymize_json_like for entity_name and message`

---

### Task 3: `PeriodMetricHostSeries.entity_name` とメトリクス系列配列

**Files:**
- 変更: `src/vcenter_event_assistant/services/llm_anonymization.py`
- 変更: `tests/test_llm_anonymization.py`

`digest_context` 以外のキー名で `entity_name` が現れる（`PeriodMetricHostSeries`）。再帰だけで拾えることをテストで固定する。

- [ ] **Step 1: RED テスト** — `period_metrics` 風 dict（`cpu` 配列の要素に `entity_name`）を渡し、匿名化後に実名が残らないこと。

- [ ] **Step 2: GREEN** — 既存 `anonymize_json_like` がカバーしていればテストのみ追加。足りなければキー走査ロジックを修正。

- [ ] **Step 3:** `uv run pytest tests/test_llm_anonymization.py -v` 後にコミット。

---

### Task 4: 文字列内 IPv4 のパターン置換（任意だが推奨）

**Files:**
- 変更: `src/vcenter_event_assistant/services/llm_anonymization.py`
- 変更: `tests/test_llm_anonymization.py`

- [ ] **Step 1: RED** — キーが `message` の文字列に含まれる `203.0.113.10` がトークンに置き換わるテスト（カテゴリ `ip`）。

- [ ] **Step 2: GREEN** — `message` およびテンプレ用の `anonymize_plain_text`（後述 Task 6 で再利用）を実装するか、`anonymize_json_like` の `str` 処理で IPv4 正規表現を適用。同一 IP は同一トークン。

- [ ] **Step 3:** テスト通過後コミット。

---

### Task 5: 設定フラグ `llm_anonymization_enabled`

**Files:**
- 変更: `src/vcenter_event_assistant/settings.py`
- 変更: `.env.example`
- 新規または変更: `tests/test_settings.py`（ファイルが無ければ `tests/test_llm_anonymization.py` に環境読み取りのスモークを 1 本追加で可）

- [ ] **Step 1: RED** — `Settings()` で `llm_anonymization_enabled` がデフォルト `True`（または運用方針で `False` にする場合は本計画と README を一致させる）であるテスト。環境変数 `LLM_ANONYMIZATION_ENABLED=false` で `False` になること。

- [ ] **Step 2: GREEN** — `Field(default=True)` + `validation_alias` で `LLM_ANONYMIZATION_ENABLED` を読む。

- [ ] **Step 3:** `uv run pytest` 対象テスト PASS 後コミット。

---

### Task 6: `run_period_chat` への統合（スパイで LLM に渡る文字列を検証）

**Files:**
- 変更: `src/vcenter_event_assistant/services/chat_llm.py`
- 変更: `tests/test_chat_llm.py`

**手順（設計）:**

1. `payload` 組み立て後、`messages` のコピーを取る。
2. `settings.llm_anonymization_enabled` が真のとき: `anonymize_json_like(payload)` でペイロードを置換し、`reverse_map` を得る。各 `ChatMessage.content` を `anonymize_plain_text`（Task 4 と共有）で置換。
3. 既存の `_fit_chat_payload_to_token_budget(settings, payload_anon, messages_anon)` を呼ぶ。
4. LLM から `text` を受け取ったら `deanonymize_text(text, reverse_map)` を適用してから返す。`reverse_map` が空ならそのまま。

- [ ] **Step 1: RED** — `test_chat_llm.py` に、`llm_anonymization_enabled=True` の `Settings` で `run_period_chat` を呼び、`stream_chat_to_text` のスパイが受け取る `HumanMessage` 本文に **実ホスト名が含まれない**ことを assert するテスト（`DigestContext` に `entity_name` を含む要注意グループを 1 件入れる）。

- [ ] **Step 2: GREEN** — `chat_llm.py` に統合。

- [ ] **Step 3:** 既存の `test_run_period_chat_openai_sends_multiturn` が壊れたら、`llm_anonymization_enabled=False` を渡すか、期待文字列を匿名化後に合わせる。

```bash
uv run pytest tests/test_chat_llm.py -v
```

- [ ] **Step 4: コミット**

---

### Task 7: `augment_digest_with_llm` への統合（JSON + テンプレ + 要約逆変換）

**Files:**
- 変更: `src/vcenter_event_assistant/services/digest_llm.py`
- 変更: `tests/test_digest_llm.py`

**手順:**

1. `context.model_dump(mode="json")` を dict として取得（または loads）。
2. 有効時: `anonymize_json_like` と `anonymize_plain_text(template_markdown, ...)` を**同一 `LlmAnonymizer` インスタンス**で行う（`anonymize_json_like` が内部で新規インスタンスを作る場合は、ファクトリ `anonymize_for_llm(context_dict, template_markdown) -> tuple[str, str, dict[str, str]]` にまとめる）。
3. `_trim_context_json` は匿名化**後**の dict に対して行う（文字数カットの意味がブレないようにする）。
4. LLM の `summary` に対して `deanonymize_text(summary, reverse_map)` を適用してから `merged = template_markdown.rstrip() + "\n\n" + summary.strip() + "\n"`（**テンプレは常に原文**）。

- [ ] **Step 1: RED** — `FakeListChatModel` が返す文字列にトークンを含めるスパイ／モックではなく、`stream_chat_to_text` を monkeypatch し、**渡された `HumanMessage` に実サーバ名が含まれない**こと、**merged に元のテンプレのホスト名が残る**ことを検証。

- [ ] **Step 2: GREEN** — `digest_llm.py` 実装。

- [ ] **Step 3:**

```bash
uv run pytest tests/test_digest_llm.py -v
```

- [ ] **Step 4: コミット**

---

### Task 8: 回帰防止 — チャット API 結合（任意）

**Files:**
- 変更: `tests/test_chat_api.py`

既存の `post_chat` テストに、レスポンスの `assistant_content` がトークン文字列を含まない（匿名化オン時）ことを 1 ケース追加する。モックは既存パターンに合わせる。

- [ ] 実装後 `uv run pytest tests/test_chat_api.py -v`

---

### Task 9: ドキュメント

**Files:**
- 変更: `docs/development.md` または既存の LLM 節がある README への 1 段落（日本語）

内容: `LLM_ANONYMIZATION_ENABLED` の意味、サーバ側逆変換で UI は従来どおり実名、LLM プロバイダにはトークン化後のみ送られる旨。

---

## 自己レビュー（計画作成時）

| チェック | 結果 |
|----------|------|
| Spec の各要件にタスクが紐づくか | Goal の匿名化・ダイジェスト二重入力・要約逆変換・チャット応答逆変換は Task 1–7 でカバー |
| TBD / 「適宜」なし | トークン形式・対象キーを本文で固定 |
| 型・関数名の一貫性 | `anonymize_json_like` / `deanonymize_text` / `LlmAnonymizer` で統一 |
| フロント | サーバ逆変換のみなら必須変更なし。マップを返す仕様に変える場合は別タスク |

---

## 実装完了時の検証コマンド

```bash
cd /Users/moriyama/git/vcenter-event-assistant
uv run pytest tests/test_llm_anonymization.py tests/test_chat_llm.py tests/test_digest_llm.py -v
uv run pytest
```

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-04-llm-input-anonymization.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — タスクごとに新しいサブエージェントをdispatchし、タスク間でレビューする（superpowers:subagent-driven-development）。

2. **Inline Execution** — このセッションで executing-plans に従いチェックボックス順に実装する。

**Which approach?**（実装開始時に指定してください。）
