# 実装プラン: チャットスニペット クリック即時追記

設計: [`../specs/2026-05-03-chat-snippet-click-to-insert-design.md`](../specs/2026-05-03-chat-snippet-click-to-insert-design.md)

## タスク一覧

1. **純関数** `appendChatSampleTextToDraft` を [`frontend/src/panels/chat/appendChatSampleTextToDraft.ts`](../../frontend/src/panels/chat/appendChatSampleTextToDraft.ts) に追加し、[`appendChatSampleTextToDraft.test.ts`](../../frontend/src/panels/chat/appendChatSampleTextToDraft.test.ts) で TDD。
2. **削除** [`appendSelectedChatSampleTextsToDraft.ts`](../../frontend/src/panels/chat/appendSelectedChatSampleTextsToDraft.ts) と旧テスト（参照をすべて置換）。
3. **UI** [`ChatPanel.tsx`](../../frontend/src/panels/chat/ChatPanel.tsx): `selectedSampleIds` / トグル / 「下書きに挿入」を撤去し、各スニペットの `onClick` で `setDraft` + `appendChatSampleTextToDraft`。
4. **結合テスト** [`ChatPanel.test.tsx`](../../frontend/src/panels/chat/ChatPanel.test.tsx) を新挙動に合わせて更新。
5. **検証** `cd frontend && npm run test -- --run src/panels/chat/` および `npm run build`（必要なら lint）。

## 完了条件

- スニペットクリックのみで下書きに反映され、送信は発火しない。
- 既存の区切り・trim ルールが維持されている。
- 関連テストがすべて緑。
