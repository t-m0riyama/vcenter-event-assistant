# スコアルール利用者向けドキュメント — 設計

**日付:** 2026-05-23  
**ステータス:** 承認済み（実装に反映）  
**正本（利用者向け）:** [`docs/user-guides/score-rules.md`](../../user-guides/score-rules.md)

## 目的

イベントの **要注目スコア**（`notable_score`）と **スコアルール**（設定 → スコアルール）について、運用担当者が画面操作と他機能との関係を理解できる利用者向け正本を用意する。[`docs/user-guides/alerts.md`](../../user-guides/alerts.md) と同型の章立て・トーンとする。

## スコープ

### 含める

- 要注目スコアの意味（0〜100）と算出の概要（ベース + 加算 → クランプ）
- スコアルールの考え方（`event_type` 完全一致、加算の負数、種別ごと1件）
- サーバー保存と取り込み済みイベントへの再計算
- 設定画面の操作（追加・保存・削除・JSON エクスポート/インポート）
- アラート・概要・タイムライン・ダイジェストとの関係（相互リンク）
- FAQ（よくある切り分け）

### 含めない（YAGNI）

- ベーススコアの数値表（severity 重み・高リスク種別一覧など）— 概要1段落 + [`docs/backend.md`](../../backend.md) へ誘導
- ベーススコアの UI 編集
- アプリ内「詳細ガイドを開く」リンクの追加
- 英語版

## 章立て（`score-rules.md`）

| 節 | 内容 |
|----|------|
| §1 | 対象と読み方（役割表・用語） |
| §2 | 全体像（フロー図） |
| §3 | 要注目スコアとは（ベース概要 + 最終式） |
| §4 | スコアルールの考え方 |
| §5 | 保存と再計算 |
| §6 | 他機能との関係 |
| §7 | 画面別操作 |
| §8 | JSON バックアップ |
| §9 | FAQ |
| §10 | 関連ドキュメント |
| 付録 | アプリ内 hint との関係 |

## 相互リンク方針

| ファイル | 変更 |
|----------|------|
| [`alerts.md`](../../user-guides/alerts.md) | §3 を短縮し `score-rules.md` を正本としてリンク。§9 関連表に1行追加 |
| [`README.md`](../../../README.md) | ドキュメント一覧に追加 |
| [`backend.md`](../../backend.md) | event_score / スコア節付近に利用者向け正本リンク |
| [`frontend.md`](../../frontend.md) | スコアルール節に user-guides リンク（任意・実施） |

`alerts.md` のアラート詳細は維持し、スコアの深掘りは `score-rules.md` に集約する。

## 実装との一致（検証ポイント）

- `final_notable_score` / `clamp_notable_total`: [`notable.py`](../../../src/vcenter_event_assistant/rules/notable.py)
- 再計算: [`event_scores.py`](../../../src/vcenter_event_assistant/services/event_scores.py)
- JSON `format`: `vea-event-score-rules`（[`schemas.ts`](../../../frontend/src/api/schemas.ts)）
- 概要の 24h 要注意件数: `notable_score >= 40`（[`dashboard.py`](../../../src/vcenter_event_assistant/api/routes/dashboard.py)）
- イベント一覧の列名: **スコア**（要注目スコアの表示値）

## 受け入れ条件

- [x] 利用者が設定 → スコアルールのみで操作手順を追える
- [x] `alerts.md` §3 の重複が最小（リンク中心）
- [x] ベーススコアの詳細数値表がない（概要のみ）
- [x] 相対リンクが切れていない
