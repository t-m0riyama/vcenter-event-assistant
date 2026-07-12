# チャットの WEB 関連チェックの一本化（2026-07-12 grilling）

チャットパネルに「WEB」を名乗るチェックが 2 つあり紛らわしい、という課題への対応。
`/grill-me` セッションで確定した設計判断のまとめ。

## 背景（現状）

| チェック | 場所 | 実体 |
|----------|------|------|
| 「WEB 調査情報を応答に付記（高スコアイベントの調査キャッシュ）」`includeResearch` | ChatContextBar（デフォルト ON・localStorage 永続化） | **調査キャッシュ添付**。research サービスが生成済みの過去の高スコアイベント調査結果を、LLM 応答の後にサーバ側で連結する（`routes/chat.py` の `build_research_attachment_markdown`）。ライブ検索は発生しない |
| 「WEB 検索を許可」`enableWebSearch` | ChatInputBar（デフォルト OFF・非永続） | **ライブ WEB 検索**。当該メッセージの応答生成中に LLM が function calling で外部検索（Tavily）を発行できる |

紛らわしさの正体は「意味の違う 2 機能が両方 "WEB" を名乗っている」こと。
当初の依頼文の「グローバルのチェック」は前者（`includeResearch`）を指す。

## 確定した設計判断

| # | 論点 | 決定 | 理由・補足 |
|---|------|------|-----------|
| U-1 | `includeResearch` チェックボックス | **撤去し、調査キャッシュは常に付記** | 現在のデフォルト ON を固定化。キャッシュ添付は DB 参照のみで外部送出・コスト増がなく、選択させる価値が薄い。チェックは「WEB 検索を許可」の 1 つだけになる |
| U-2 | API の `ChatRequest.include_research` | **残す（default true）** | API 直叩きクライアントは `false` 明示で付記を抑止可能。サーバ側コードは変更なし。UI からは送らない（default に委ねる） |
| U-3 | 「WEB 検索を許可」チェック | **現状維持** | 表示条件（検索プロバイダ構成時のみ = `chat_web_search_available`）も、リロードで OFF に戻る非永続挙動も変えない。外部検索は明示オプトインのまま |
| U-4 | プロバイダ未構成時の見せ方 | **現状維持（チェックボックス非表示）** | 閉域網等では従来どおり何も出さない |

## 実装範囲（フロントのみ）

- `ChatContextBar.tsx`: 「WEB 調査情報」セクションと `includeResearch` / `setIncludeResearch` props を削除
- `ChatPanel.tsx`: 同 props の受け渡しを削除
- `useChatPanelController.ts`: `includeResearch` state・スナップショット復元・永続化・リクエスト本文の `include_research` を削除
- `chatPanelStorage.ts`: スナップショットスキーマから `includeResearch` を削除
  （zod は未知フィールドを strip するので、旧スナップショットに残る値は無害に無視される）
- 各テスト（ChatPanel / chatPanelStorage 等）の追随
- バックエンド変更なし。`include_research`（default true）の既存テストはそのまま有効

## 影響・注意

- UI から調査キャッシュ付記を止める手段はなくなる（API の `include_research: false` のみ）
- ユーザーガイド系ドキュメント（`2026-05-23-chat-user-guide-design.md` 等）にこのチェックの記述があれば追随が必要
