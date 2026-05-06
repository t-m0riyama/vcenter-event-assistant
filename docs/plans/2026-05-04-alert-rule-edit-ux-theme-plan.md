# アラート編集 UX・テーマ統一（追補プラン）

**関連:** [既存アラートルールの編集機能（インライン編集）](./2026-05-04-alert-rule-edit-design.md) の実装後フォロー。編集の発見性と展開行の見た目を改善する。

## 概要

アラートルール一覧の「編集の発見性」をイベント種別ガイドに近い展開 UI（シェブロン・ホバー・背景階層）で揃え、展開行の背景が未定義トークンでライト固定色になっている不具合をテーマ変数ベースに修正する。

## 実装タスク

- [ ] [`AlertRulesPanel.tsx`](../../frontend/src/panels/settings/AlertRulesPanel.tsx): `tr` の行クリックをやめ、シェブロン付き `button` + `aria-expanded` / `handleExpandRow` に集約
- [ ] [`AlertRulesPanel.css`](../../frontend/src/panels/settings/AlertRulesPanel.css): サマリ行を elevated + hover、展開行を theme トークン＋内側パネル（`add-rule-form` 系）に統一し `--color-background-subtle` を廃止
- [ ] ライト／ダークの見た目確認と `npm run build`（`frontend/`）
- [ ] （任意）[編集機能設計](./2026-05-04-alert-rule-edit-design.md) の「UX」節を、行クリックからシェブロン／トグルに更新した旨で短く追記

## 背景（現状の根拠）

- 編集は [`AlertRulesPanel.tsx`](../../frontend/src/panels/settings/AlertRulesPanel.tsx) で `<tr className="editable-row">` 全体の `onClick` により展開するだけで、折りたたみ状態を示すシェブロンや「編集」ラベルがない。レベル／有効／削除は `stopPropagation` されているが、**残りの行が「クリック可能」と分かりにくい**。
- 展開行は [`AlertRulesPanel.css`](../../frontend/src/panels/settings/AlertRulesPanel.css) の `.edit-row td` が `var(--color-background-subtle, #f7f7fb)` を参照しているが、[`variables.css`](../../frontend/src/styles/variables.css) に **`--color-background-subtle` は未定義**のため常に `#f7f7fb` になり、ダークテーマでは新規作成フォーム（`--color-background-secondary`）やイベント種別ガイド（`--color-background-elevated` / `color-mix` ホバー）と**階調がずれる**。

## 方針（ユーザー選択: ガイド同様のシェブロン系）

イベント種別ガイド（[`EventTypeGuidesPanel.css`](../../frontend/src/panels/settings/EventTypeGuidesPanel.css)）のパターンを参照し、**「サマリ行＝一段上げた面＋ホバー」「展開本体＝通常背景＋内側パディング」**の階層に寄せる。テーブル構造は維持しつつ、視覚言語を揃える。

## アプローチ案（実装で採用するのは推奨のみ）

| 案 | 内容 | 長所 | 短所 |
|----|------|------|------|
| **A（推奨）** | 1列目（または名前セル内）に **開閉用ボタン＋シェブロン**（`aria-expanded` / `aria-controls`）。行全体の `onClick` はやめ、名前＋シェブロン（必要なら条件セル）から展開 | ガイドと同じ「開いている／閉じている」が一目で分かる。誤タップが減る | `tr` のマークアップと CSS が少し増える |
| B | `<details>` で行を包む | セマンティクスは良い | [編集機能設計](./2026-05-04-alert-rule-edit-design.md) でも触れている通り、**テーブル内の `<details>` はレイアウト・キーボード挙動のリスク**があり、現状の 2 行 `Fragment` 方式の方が安全 |
| C | 行クリック維持＋シェブロンのみ装飾 | 変更が小さい | 「どこを押すか」が依然あいまい |

**採用: 案 A**（シェブロンはガイドと同様に展開で 90° 回転する CSS を共通化またはローカル複製）。

## 具体的な変更内容

### 1. TSX（[`AlertRulesPanel.tsx`](../../frontend/src/panels/settings/AlertRulesPanel.tsx)）

- 折りたたみ行から **`onClick` を `tr` から除去**。
- **開閉トリガー**: 例として先頭列に `<button type="button" className="alert-rule-row__toggle" …>` を置き、中にシェブロン（インライン SVG または既存アイコンがあれば流用）。`expandedId === r.id` で `aria-expanded` とクラス（`alert-rule-row__chevron--open` 等）を切り替え。
- `handleExpandRow` はボタン（＋必要なら名前セル内のラップ）からのみ呼ぶ。レベル／有効／削除は現状どおり `stopPropagation` 不要になる場合もあるが、**トグルと競合しないよう**ボタン以外のセルはクリックで展開しない設計にすると誤操作が減る（名前＋条件の短い説明をクリックで展開するかは実装時に 1 箇所に統一）。
- **キーボード**: トグルに `Enter` / `Space` で開閉（`<button>` なら標準で満たす）。

### 2. CSS（[`AlertRulesPanel.css`](../../frontend/src/panels/settings/AlertRulesPanel.css)）

- **サマリ行**: ガイドの `.event-type-guide-row__summary` に近づける — `background: var(--color-background-elevated)`、`:hover` で `color-mix(in srgb, var(--color-border) 35%, var(--color-background-elevated))`（同ファイルの値をコピーで可）。
- **展開行**: `.edit-row td` の背景を **`var(--color-background)`**（ガイドの `.event-type-guide-row__body` と同様）にし、**内側にラッパー**（例: `.alert-rule-edit-panel`）を置いて `add-rule-form` と同様の `border` / `border-radius` / `padding` / `background: var(--color-background-secondary)` を適用するか、ガイドの「本文エリア」に合わせて **境界線のみ＋背景は一段下げる** のどちらかに統一（推奨: 新規作成フォームと同じ **secondary + border** で「設定フォーム」系として一貫）。
- **`--color-background-subtle` 依存を削除**（フォールバック色は使わない）。

### 3. ドキュメント（任意・小）

- 実装後、[編集機能設計](./2026-05-04-alert-rule-edit-design.md) の「UX」節に 1〜2 行追記し、「行クリック」から「シェブロン／トグルボタン」に更新した旨を残す（計画書と実装の乖離防止）。

### 4. 検証

- ライト／ダークの両方で展開前後のコントラストとホバーを目視。
- `npm run build`（フロント）。

## スコープ外

- API や PATCH ロジックの変更（既に実装済みなら触れない）。
- イベント種別ガイドの CSS を共通ファイルに切り出す大規模リファクタ（必要なら別タスク）。

## リスク

- トグルを名前列だけにすると列幅が変わる — シェブロンは `flex-shrink: 0` で固定幅にする（ガイドと同様）。
