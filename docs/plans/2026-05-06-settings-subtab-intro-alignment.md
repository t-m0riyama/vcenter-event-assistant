---
name: settings-subtab-intro-alignment
overview: 設定タブ配下の 6 サブタブの冒頭テキストを「2〜3 文・スコープ + 保存先 + 主要挙動」の中粒度 `<p className="hint">` に統一し、サブタブ名と重複する `<h2>` は削除する。実装は隔離 worktree 上で TDD（Red→Green→Refactor）にて進め、Python/pytest はすべて `uv` 経由で実行する。
todos:
  - id: setup-worktree
    content: 実装開始前に `using-git-worktrees` に沿って作業用 worktree を作成し、ベースライン確認を行う
    status: pending
  - id: enforce-tdd
    content: 全変更を TDD（Red→Green→Refactor）で進める。失敗するテストを先に追加し、Red を確認してから本実装に着手する
    status: pending
  - id: enforce-uv
    content: Python の実行・テスト・依存追加はすべて `uv`（`uv run`, `uv sync`, `uv add` など）経由で行う
    status: pending
  - id: doc
    content: 本ファイル（docs/plans/2026-05-06-settings-subtab-intro-alignment.md）を最新化しコミット
    status: pending
  - id: tests-frontend-red
    content: "`App.settings-subtabs.test.tsx` などに、各サブタブの冒頭が `p.hint` であり所定の文言・要素を含むことを検証する失敗テストを追加（RED）"
    status: pending
  - id: general
    content: GeneralSettingsPanel.tsx の冒頭に概要 hint を追加（GREEN）
    status: pending
  - id: score
    content: ScoreRulesPanel.tsx の冒頭 hint を中粒度に書き換え（GREEN）
    status: pending
  - id: guides
    content: EventTypeGuidesPanel.tsx の冒頭 hint に保存先を追記（GREEN）
    status: pending
  - id: vcenters
    content: VCentersPanel.tsx の <h2>登録</h2> の上に概要 hint を追加（GREEN）
    status: pending
  - id: chat
    content: ChatSamplePromptsPanel.tsx の <h2>プロンプトスニペット</h2> を削除し、hint を整理（GREEN）
    status: pending
  - id: alerts
    content: AlertRulesPanel.tsx の <h2>アラートルール設定</h2> を削除し、ヘッダー行に概要 hint を配置（GREEN）
    status: pending
  - id: refactor
    content: 重複や CSS 不整合を整える REFACTOR を行い、グリーン維持を確認
    status: pending
  - id: verify
    content: "`cd frontend && npm run typecheck && npm test` と `uv run pytest` の双方を実行し、全テスト通過を確認"
    status: pending
isProject: false
---

# 設定サブタブ冒頭テキストの記載レベル統一 実装計画

## 目的

設定タブ配下の 6 サブタブで、冒頭テキストの粒度・有無・要素がバラついている状態を解消し、ユーザーが各サブタブを開いた直後に「何を管理するタブか」「どこに保存されるか」を一貫した粒度で把握できるようにする。

## 実装前提（必須）

- **隔離ワークツリー**: 実装開始前に `using-git-worktrees` を使用し、`main` から派生した隔離 worktree を作成して作業する。`main` への直接コミットや既存ワークツリー混在は禁止。
- **TDD**: 以後の実装は `test-driven-development` に従い、**必ず Red→Green→Refactor の順** で進める。失敗するテストを先に追加し、失敗を確認する前に本番コードを書かない。
- **uv 経由の Python 実行**: Python のスクリプト実行・テスト・依存管理はすべて `uv` 経由で行う。具体的には:
  - スクリプト実行: `uv run python ...`
  - テスト: `uv run pytest`（または `uv run pytest -k <pattern>`）
  - 依存追加・削除: `uv add <pkg>` / `uv remove <pkg>`
  - 同期: `uv sync`
  - `pip` / `pip-tools` / `poetry` を直接呼ぶことは禁止。
- **Frontend テスト**: 既存通り `cd frontend && npm test` / `npm run typecheck` を使用。

## 統一後の方針

各サブタブの冒頭に、共通フォーマットの `<p className="hint">` 概要文を必ず 1 つ置く。

- **粒度**: 2〜3 文の中粒度
- **必ず触れる要素**: (1) このタブで何を管理するか / (2) 保存先（サーバー or ブラウザ localStorage） / (3) 主要挙動・他タブへの影響を 1 点
- **位置**: パネル直下、`<h2>` よりも前
- サブタブ名と重複する `<h2>`（「アラートルール設定」「プロンプトスニペット」）は削除し、本文構造をシンプル化

統一後の各パネル骨格:

```tsx
<div className="panel">
  <p className="hint">{2〜3 文の概要}</p>
  {/* （AlertRules のみ）右上に「新規ルール追加」ボタン行を維持 */}
  <h2>...</h2>
  ...
</div>
```

## サブタブ別の差分

### 1. 一般 ([`frontend/src/panels/settings/GeneralSettingsPanel.tsx`](/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/settings/GeneralSettingsPanel.tsx))

- 冒頭にパネル概要 hint を新規追加。既存の各フィールドの `<p className="hint">` は据え置き。

提案文:

> このアプリの表示・更新動作に関する個人向け設定です。すべてこのブラウザの localStorage に保存され、サーバーや他端末・他ブラウザには共有されません。

### 2. スコアルール ([`frontend/src/panels/settings/ScoreRulesPanel.tsx`](/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/settings/ScoreRulesPanel.tsx))

- 既存冒頭 hint を「保存先 = サーバー」を明示する形に書き換え（粒度合わせ）。

提案文（差し替え）:

> イベント種別（`event_type`）ごとに、ルールベースのスコアへ加算する値（最終スコアは 0〜100）をサーバーに登録します。保存・変更・削除時には、既に取り込み済みのイベントのスコアにも再計算が反映されます。

### 3. イベント種別ガイド ([`frontend/src/panels/settings/EventTypeGuidesPanel.tsx`](/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/settings/EventTypeGuidesPanel.tsx))

- 既存冒頭 hint に保存先を追記し 2 文に整える。

提案文（差し替え）:

> イベント種別（`event_type`、収集ログの種別文字列と完全一致）ごとに、一般的な意味・想定される原因・対処方法をサーバーに登録します。「対処が必要」をオンにすると、概要・イベント一覧で該当行を強調表示します。

### 4. vCenter ([`frontend/src/panels/settings/VCentersPanel.tsx`](/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/settings/VCentersPanel.tsx))

- `<h2>登録</h2>` の上に概要 hint を新規追加。

提案文:

> イベント・メトリクスの収集元となる vCenter Server の接続先をサーバーに登録します。パスワードは暗号化のうえ保存され、「有効」にした接続だけが定期収集と問い合わせの対象になります。

### 5. チャットサンプル ([`frontend/src/panels/settings/ChatSamplePromptsPanel.tsx`](/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/settings/ChatSamplePromptsPanel.tsx))

- `<h2>プロンプトスニペット</h2>` を削除（サブタブ名と重複）。
- 既存の 1 段目 hint をパネル冒頭の概要に整理（保存先 = localStorage を含む）。
- 2 段目 hint「ラベルと本文の両方に文字が入っている行だけが…」は編集ルールなので、`<h2>一覧</h2>` セクションへ移設し残す。

提案文（冒頭）:

> チャットタブの「サンプルの質問」チップに並ぶ行を編集します。このブラウザの localStorage に保存され、コード同梱の既定サンプルもここから編集・削除できます。

### 6. アラートルール ([`frontend/src/panels/settings/AlertRulesPanel.tsx`](/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/settings/AlertRulesPanel.tsx))

- `<h2>アラートルール設定</h2>` を削除（サブタブ名と重複）。
- 既存の `.alert-rules-panel-header` 行は維持し、左側に概要 hint、右側に「新規ルール追加」ボタンを並べる構成に変更（CSS は据え置き、必要があれば微調整）。

提案文:

> イベントスコアやメトリクス閾値に基づいてアラートを発生させる条件をサーバーに登録します。各ルールはクリティカル/エラー/警告のいずれかのレベルを持ち、「有効」にしたルールだけがアラート判定の対象になります。

## 実装ステップ

1. `using-git-worktrees` に従って worktree を作成し、`uv sync` と `cd frontend && npm install` でベースラインをセットアップする。`uv run pytest` と `cd frontend && npm test` をベースラインとして実行し、現状グリーンを確認。
2. **RED(Frontend)**: `App.settings-subtabs.test.tsx` または各 `*Panel.test.tsx` に、6 サブタブそれぞれについて
   - 冒頭の最初の段落が `p.hint` であり、想定文言の主要キーワード（例: 「localStorage に保存」「サーバーに登録」「暗号化」など）を含むこと
   - `<h2>アラートルール設定</h2>`・`<h2>プロンプトスニペット</h2>` が存在しないこと
   を検証する失敗テストを追加し、`npm test` で **RED を確認**する。
3. **GREEN(Frontend)**: 6 ファイルを順次修正して全テストを通す（順序は General → ScoreRules → EventTypeGuides → VCenters → ChatSamplePrompts → AlertRules を推奨）。
4. **REFACTOR**: 文言の文体（「〜します」「〜です」）を統一し、CSS で hint とボタンの配置に崩れがあれば微修正。`npm run typecheck` 通過、`npm test` グリーン維持を確認。
5. バックエンドへ波及する変更は本タスクでは無いが、念のため `uv run pytest` を実行し、回帰しないことを確認する。
6. プラン todo を完了状態に更新し、コミットメッセージは Conventional Commits（例: `refactor(settings): align sub-tab intro hints to medium granularity`）で作成。`main` 直接コミットは禁止。

## 影響ファイル

- `frontend/src/panels/settings/GeneralSettingsPanel.tsx`
- `frontend/src/panels/settings/ScoreRulesPanel.tsx`
- `frontend/src/panels/settings/EventTypeGuidesPanel.tsx`
- `frontend/src/panels/settings/VCentersPanel.tsx`
- `frontend/src/panels/settings/ChatSamplePromptsPanel.tsx`
- `frontend/src/panels/settings/AlertRulesPanel.tsx`
- `frontend/src/App.settings-subtabs.test.tsx`（必要に応じてテスト追加）
- 既存の各 `*Panel.test.tsx`（必要に応じて）
- `frontend/src/panels/settings/AlertRulesPanel.css`（hint とボタンの横並びで崩れる場合のみ）

## 検証

- `cd frontend && npm run typecheck` → エラーゼロ
- `cd frontend && npm test` → 既存・追加テスト全てグリーン
- `uv run pytest` → 既存バックエンドテスト全てグリーン（回帰なきことの確認）
- 開発サーバ（`docker compose up` もしくは `cd frontend && npm run dev` + `uv run uvicorn ...`）で 6 サブタブを目視。冒頭が `<p className="hint">` の 2〜3 文になり、サブタブ名と重複する `<h2>` が消えていることを確認。

## 影響範囲

- API スキーマ変更なし、DB スキーマ変更なし、バックエンド改修なし
- フロントエンドの設定タブ内 UI コピーと一部 DOM 構造の変更のみ
