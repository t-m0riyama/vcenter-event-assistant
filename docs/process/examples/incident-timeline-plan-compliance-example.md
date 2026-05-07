# 記入例: Incident Timeline フォローアップ

このファイルは、テンプレート4種を1案件でどう使うかを示す通し記入例。

## 1) チェックリスト抜粋
- プラン: `docs/plans/2026-05-07-chat-preview-modal-timeline-visibility-fix-plan.md`
- ブランチ: `feature/incident-timeline-mvp`
- 判定: 完了

## 2) 要件ID-テスト証跡マッピング
| 要件ID | 要件概要 | 判定基準 | 対応テスト/確認手順 | 結果 | 備考 |
|---|---|---|---|---|---|
| REQ-01 | モーダルを閉じてもタイムラインを保持 | タイムラインがDOM上に残る | `ChatPanel.test.tsx` `it('モーダルを閉じてもタイムラインは保持される')` | PASS |  |
| REQ-02 | プレビュー取得時にモーダルを開く | プレビュー後にモーダル表示 | `ChatPanel.test.tsx` のプレビューテスト | PASS |  |

## 3) PR本文の Plan Compliance 抜粋
```md
## Plan Compliance
### 対象プラン
- `docs/plans/2026-05-07-chat-preview-modal-timeline-visibility-fix-plan.md`

### 要件対応状況
| 要件ID | ステータス | 対応コード | 対応テスト/証跡 | 備考 |
|---|---|---|---|---|
| REQ-01 | 満たす | `frontend/src/panels/chat/ChatPanel.tsx` | `it('モーダルを閉じてもタイムラインは保持される')` |  |
| REQ-02 | 満たす | `frontend/src/panels/chat/ChatPanel.tsx` | `vitest run ...ChatPanel.test.tsx` |  |
```

## 4) 変更申請（必要時のみ）
今回のケースでは仕様変更なしのため申請なし。  
もし「横軸タイムラインを縦積みに変更」する場合は、`plan-change-request-template.md` を起票して合意後に実装する。
