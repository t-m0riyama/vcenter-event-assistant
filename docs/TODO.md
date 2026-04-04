# TODO（追跡用）

本ファイルは、実装済み機能の**フォローアップ**や**未着手の拡張**を一覧する。Issue / プロジェクトボードへ移す場合はここから切り出す。

---

## チャット話題ガード（オフトピック連続・クールダウン）のフォローアップ

MVP はプロセス内メモリ（[`MemoryChatTopicGuardStore`](../src/vcenter_event_assistant/services/chat_topic_guard_store.py)）・[`classify_chat_user_message`](../src/vcenter_event_assistant/services/chat_topic_classify.py)・[`post_chat` のガード](../src/vcenter_event_assistant/api/routes/chat.py)・フロントの `chat_session_id` / 429 処理まで実装済み。以下は**未実装または任意**。

### インフラ・一貫性（マルチワーカー）

- [ ] **共有ストア（Redis 推奨）**: `ChatTopicGuardStore` の Redis 実装。キー例 `chat_topic_guard:{session_id}`、JSON で `consecutive_off_topic` / `blocked_until`、TTL で掃除。
- [ ] **設定**: 例 `CHAT_TOPIC_GUARD_REDIS_URL`（または既存 Redis 設定との統合）。`get_chat_topic_guard_store()` を設定で Memory / Redis に切り替え。
- [ ] **障害時フォールバック**: Redis 不通時はメモリに落とす／ガード無効／503 など、運用方針を決めて実装。
- [ ] **LB スティッキーのみ運用する場合**: ワーカー再起動でストライクが消えること、メモリストアがワーカー間で共有されないことを README または [development.md](development.md) に短く明記。

### 観測性・運用

- [ ] **構造化ログ**: `post_chat` でセッション ID の短縮ハッシュ、`on_topic` 判定、429 返却時の情報を info 相当で記録（現状は分類のパース失敗・LLM 失敗時の warning が中心）。
- [ ] **メトリクス（任意）**: 分類レイテンシ、オフトピック率、429 件数（Prometheus 等は別方針なら省略可）。

### プロダクト・UX（別要件扱い）

- [ ] **セッション境界の拡張**: 現状はタブ単位 `sessionStorage`。同一ユーザーがブラウザ横断でストライクを共有するには `localStorage` または認証ユーザー ID キー（プライバシー・タブ分離とのトレードオフ要検討）。
- [ ] **分類専用モデル（任意）**: 現状はチャット用 LLM プロファイルと同一。分類だけ安価・高速モデルに分ける env（モデル ID / タイムアウト）を追加するか検討。

### テスト

- [ ] **API 統合**: `utc_now` をモンキーパッチしてクールダウン**期限切れ後**に再送が成功することを `tests/test_chat_api.py` 等で検証。
- [ ] **フロント**: `ChatPanel.test.tsx` で 429（`ApiHttpError`）時のクールダウン・ユーザメッセージの巻き戻し・`onError` 文言を検証。

### ドキュメント

- [ ] **開発者向け**: 話題ガードの有効条件（`chat_session_id` 未送信時はサーバー側ストライクを持たない）、環境変数、マルチワーカー時の注意を [development.md](development.md) または README に 1 セクション追加。

### メタ

- [ ] **計画ファイルの整理**: `.cursor/plans/チャット範囲外対策_*.plan.md` の frontmatter `todos` が実装完了後も `pending` のままなら、完了へ更新または本ファイルへ一本化。

---

## その他

（プロジェクト全体の TODO は必要に応じてここに追記する。）
