# チャット WEB 検索条件のユーザー指定（2026-07-29）

Settings「チャット」タブで、ライブ WEB 検索の **スコープ** と **積極度** をユーザーが選べるようにする。
入力欄の「WEB 検索を許可」オプトインは現状維持（都度・非永続）。設定値は許可 ON 時の振る舞いだけを決める。

## 背景

- 経路 B（チャット WEB 検索）のソフトゲートは、ツール docstring と
  `CHAT_WEB_SEARCH_GUIDANCE`（`compose_chat_system_prompt`）で固定されている
  （#154 で VMware 運用全般・関連製品まで緩和済み）
- ユーザーによって「障害だけに絞りたい」「もっと積極的に KB を引きたい」等の好みが違う
- Settings「チャット」は現状サンプルプロンプト CRUD のみ（`ChatSamplePromptsPanel`）

## 確定した設計判断

| # | 論点 | 決定 | 理由・補足 |
|---|------|------|-----------|
| P-1 | 何を設定するか | **スコープ + 積極度** の 2 軸プリセット | 自由記述は品質・安全方針のばらつきが大きい |
| P-2 | 保存場所 | **ブラウザ localStorage に永続** | サンプルプロンプトと同様。サーバにユーザー設定を持たない |
| P-3 | 許可トグルとの関係 | **入力欄トグルは現状どおり**（都度 ON・非永続）。Settings は許可 ON 時の振る舞いのみ | 外部送出の明示オプトイン（U-3）を維持 |
| P-4 | 実装方式 | **API に enum を載せ、サーバでプロンプト/ツール説明を切替** | フロントだけに断片を持つと docs・出典方針とずれやすい |
| P-5 | 既定値 | `scope=vmware_ecosystem` + `aggressiveness=balanced` | #154 時点の現行文言と同等 |
| P-6 | プロバイダ未構成時の Settings UI | **常時表示**（設定は保存可） | 許可トグルは従来どおり非表示のため実効なし。閉域でも設定準備可能 |
| P-7 | preview | **変更なし** | 検索ツールを使わない経路 |

## UI

Settings サブタブ `chat_samples`（ナビラベル「チャット」）を拡張する。

```
設定 → チャット
├─ WEB 検索の条件          ← 新規セクション
│   ├─ 検索スコープ（select）
│   ├─ 検索の積極度（select）
│   └─ 補足文
└─ サンプル質問            ← 既存 ChatSamplePromptsPanel
```

| 項目 | 内容 |
|------|------|
| 新コンポーネント | `ChatWebSearchPrefsPanel`（prefs の表示・変更） |
| 合成 | `App.tsx` で prefs パネル + サンプルパネルを縦に並べる。`panelLabel` を「チャット設定」に変更 |
| 補足文 | 「入力欄の『WEB 検索を許可』が ON のときに適用されます。」 |
| 入力欄 | `ChatInputBar` の許可チェックは変更しない |

### 選択肢

| フィールド | 値 | 表示ラベル | 既定 |
|------------|-----|------------|------|
| スコープ | `incidents` | 障害・イベント | |
| | `vsphere_ops` | vSphere 運用全般 | |
| | `vmware_ecosystem` | VMware 関連製品まで | **既定** |
| 積極度 | `conservative` | 必要なときだけ | |
| | `balanced` | バランス | **既定** |
| | `aggressive` | 積極的に検索 | |

## 永続化（フロント）

| 項目 | 内容 |
|------|------|
| キー | `vea.chat_web_search_prefs` |
| JSON | `{ "scope": "<enum>", "aggressiveness": "<enum>" }` |
| 不正値 | パース失敗・未知値は既定にフォールバック |
| 実装パターン | `chatWebSearchPrefsStorage.ts` + Context Provider + `useChatWebSearchPrefs`（`useChatSamplePrompts` と同型。Settings と Chat パネルの両方から読む） |
| 送信 | `useChatPanelController` が prefs を読み、`enable_web_search === true` のときだけリクエスト body に載せる |

## API

`ChatRequest` に追加（Pydantic / Zod 両方）:

| フィールド | 型 | 省略時 |
|------------|-----|--------|
| `web_search_scope` | `"incidents" \| "vsphere_ops" \| "vmware_ecosystem"` | `vmware_ecosystem` |
| `web_search_aggressiveness` | `"conservative" \| "balanced" \| "aggressive"` | `balanced` |

ルール:

1. `enable_web_search=false` または検索プロバイダ未構成 → 両フィールドは無視（ツール非バインド・指針なし）
2. 未知値 → 422（フロントは enum のみ送信）
3. `routes/chat.py` → `run_period_chat(..., web_search_scope=..., web_search_aggressiveness=...)`
4. プレビュー API はフィールドを受け取っても検索には使わない（送らなくてよい）

## サーバ側の振る舞い

ハードゲート（オプトイン・sanitize・`CHAT_WEB_SEARCH_MAX_CALLS`）は不変。
ソフトゲートのみを prefs で切替する。

### スコープ → 対象範囲

| scope | ツール説明・指針の対象 |
|-------|------------------------|
| `incidents` | 障害・イベントの原因・対処・関連 KB |
| `vsphere_ops` | 上記 + 設定手順・ベストプラクティス・互換性（vSphere 中心） |
| `vmware_ecosystem` | 上記 + ESXi / vCenter / NSX / vSAN 等（現行 #154） |

固有名・IP・匿名化トークンをクエリに含めない指示は全スコープ共通。

### 積極度 → 検索してよい / しない

| aggressiveness | トーン |
|----------------|--------|
| `conservative` | JSON/会話で足りそうなら検索しない。一般 KB・手順が明確に必要なときだけ |
| `balanced` | 現行（足りるときはしない / 一般手順・KB が必要ならする） |
| `aggressive` | 一般知識・手順・KB で答えの質が上がりそうなら積極的に検索。要約・数値の単純列挙のみ控える |

実装の置き場:

- `compose_chat_system_prompt(*, enable_web_search, scope=..., aggressiveness=...)` が指針文言を組み立てる
- `web_search` ツール説明は **scope のみ** で切替（積極度はシステム指針側）。LangChain / Copilot の両経路で同じ説明文を使う
- スコープ別・積極度別の文言テーブルは `chat_llm_payload.py` に集約する（クラス docstring 固定文字列には依存しない）

## ドキュメント

- `docs/web-search-conditions.md` 経路 B: ユーザー指定の scope / aggressiveness を追記
- チャット利用者ガイド（`docs/superpowers/specs` 配下の chat user guide、または README からリンクされるガイド）に Settings「チャット」の項目を短く追記。該当セクションが無ければ `web-search-conditions.md` へのリンク追加で足りる

## テスト

- storage: 正常・不正 JSON・未知 enum → 既定フォールバック
- API: フィールドが `run_period_chat` に渡る / 未知値 422
- LLM: scope・aggressiveness の組でシステムプロンプト（とツール説明）が変わる
- `enable_web_search=false` またはプロバイダなし → 指針なし・フィールド無視
- フロント: Settings で変更すると localStorage に書き込まれ、送信 body に載る（許可 ON 時のみ）

## 非目標

- 入力欄での scope / aggressiveness の都度上書き UI
- サーバ側ユーザー設定 DB
- 検索プロバイダ・`CHAT_WEB_SEARCH_MAX_CALLS` のユーザー変更
- 事前調査ジョブ（経路 A）のクエリ変更
- 「WEB 検索を許可」デフォルトの永続化（P-3 で対象外）

## データフロー

```
Settings ChatWebSearchPrefsPanel
  → localStorage vea.chat_web_search_prefs
  → useChatPanelController (on send, if enable_web_search)
  → POST /api/chat { enable_web_search, web_search_scope, web_search_aggressiveness }
  → run_period_chat
  → compose_chat_system_prompt + web_search tool description
  → LLM tool loop (optional)
```
