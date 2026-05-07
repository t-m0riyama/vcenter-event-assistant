# PR本文テンプレ: Plan Compliance

以下をPR本文に貼り付けて利用する。

```md
## Plan Compliance

### 対象プラン
- `<docs/plans/...>`

### 要件対応状況
| 要件ID | ステータス | 対応コード | 対応テスト/証跡 | 備考 |
|---|---|---|---|---|
| REQ-01 | 満たす | `frontend/src/...` | `vitest ...` / `it('...')` |  |
| REQ-02 | 満たす | `src/...` | `pytest ...` / `test_...` |  |
| REQ-03 | 未対応 | なし | なし | 次PRで対応予定 |

### 仕様変更（プランとの差分）
- なし
<!-- 差分がある場合は以下を記載 -->
<!-- - 変更申請: docs/process/plan-change-request-template.md を使用 -->
<!-- - 承認者: <name> -->
<!-- - 合意リンク: <issue/pr/comment> -->

### テスト実行結果
- [ ] 要件対応テスト: `<command>`（PASS）
- [ ] 回帰テスト: `<command>`（PASS）
- [ ] 手動確認: `<手順>`（PASS）
```

## 記入ルール
- `ステータス` は `満たす / 未対応 / 変更提案` のいずれかに限定する。
- `未対応` または `変更提案` がある場合は、理由と次アクションを必ず記載する。
- プラン差分がある場合、変更申請の合意情報がないPRはマージしない。

## 記入例
```md
## Plan Compliance

### 対象プラン
- `docs/plans/2026-05-07-chat-preview-modal-timeline-visibility-fix-plan.md`

### 要件対応状況
| 要件ID | ステータス | 対応コード | 対応テスト/証跡 | 備考 |
|---|---|---|---|---|
| REQ-01 | 満たす | `frontend/src/panels/chat/ChatPanel.tsx` | `ChatPanel.test.tsx` `it('モーダルを閉じてもタイムラインは保持される')` |  |
| REQ-02 | 満たす | `frontend/src/panels/chat/ChatPanel.tsx` | `vitest run src/panels/chat/ChatPanel.test.tsx` |  |
| REQ-03 | 未対応 | なし | なし | 「再表示導線の改善」は次PRで対応 |

### 仕様変更（プランとの差分）
- なし

### テスト実行結果
- [x] 要件対応テスト: `npm run --prefix frontend test -- src/panels/chat/ChatPanel.test.tsx`（PASS）
- [x] 回帰テスト: `npm run --prefix frontend test -- src/panels/chat/IncidentTimelinePanel.test.tsx src/api/schemas.test.ts`（PASS）
- [x] 手動確認: プレビュー表示→閉じる→タイムライン残存を確認（PASS）
```
