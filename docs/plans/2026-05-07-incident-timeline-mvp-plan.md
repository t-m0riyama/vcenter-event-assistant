# インシデント自動タイムライン生成 MVP 実装プラン

## 目的
- 初動トリアージ時間を短縮するため、チャット送信時にイベント・メトリクス・アラート履歴を時系列統合して可視化する。
- 同統合タイムラインをチャット文脈として LLM に注入し、初動対応の優先順位づけを支援する。

## 確定要件
- UI は 3段構成
  - 1段目: フィルタ（期間、vCenter、重要度、ソース）
  - 2段目: 統合タイムライン（横軸=時刻）
  - 3段目: チャット投入プレビュー
- 同一時刻に Event/Metric/Alert が複数重なる前提
- 同一時刻内の表示順は固定: `Alert → Event → Metric`
- 色分けは固定: `Alert=赤 / Event=青 / Metric=緑`
- 同一時刻の表示は上位10件まで、超過分は `+N件` で展開可能

## 変更対象
- フロント
  - [frontend/src/panels/chat/ChatPanel.tsx](frontend/src/panels/chat/ChatPanel.tsx)
  - [frontend/src/api/schemas.ts](frontend/src/api/schemas.ts)
  - 新規: `frontend/src/panels/chat/IncidentTimelinePanel.tsx`
  - 新規: `frontend/src/panels/chat/incidentTimeline.ts`
- バック
  - [src/vcenter_event_assistant/api/routes/chat.py](src/vcenter_event_assistant/api/routes/chat.py)
  - [src/vcenter_event_assistant/api/routes/alerts.py](src/vcenter_event_assistant/api/routes/alerts.py)
  - [src/vcenter_event_assistant/api/routes/events.py](src/vcenter_event_assistant/api/routes/events.py)
  - 新規: `src/vcenter_event_assistant/services/chat_incident_timeline.py`
  - APIスキーマ（`ChatPreviewResponse` など）の拡張

## 実装方針
- **作業単位**: `git worktree` を使用して実装する（`main` 直作業を避ける）
- オンデマンド統合（`/api/chat` / `/api/chat/preview` 実行時に生成）
- タイムライン列キーは時刻バケットで正規化
- 同一時刻内は種別でグルーピング後に `Alert > Event > Metric` でソート
- 1時刻列あたり `visible_items=10` と `hidden_count` を返す
- LLM入力トークン超過時は既存方針に合わせ、古い時刻列から削減

## ブランチ・ワークツリー運用
- `main` には直接コミットしない
- 例: `.worktrees/feature/incident-timeline-mvp` を作成してそこで実装する
- 実装開始前に `git branch --show-current` と `pwd` で作業先を確認する

## TDD実装順序
1. バックエンド: 同時刻重複・並び順・上位10件/hidden_count の失敗テストを先に追加
2. バックエンド: 最小実装でテストを通す
3. フロント: 色分け・並び順・`+N件` 展開の失敗テストを先に追加
4. フロント: 最小実装でテストを通す
5. `/api/chat` と `/api/chat/preview` の統合挙動テストを追加して接続

## テスト観点
- 同時刻に種類混在でも順序が常に `Alert → Event → Metric`
- 同時刻11件以上で 10件表示 + `+N件` 展開が正しい
- 色分けクラスが種別に対応して正しく付与される
- タイムライン0件時もチャット送信は継続できる
- アラート履歴取得不可時に機能劣化で継続できる

## 受け入れ条件
- 合意済みUIルール（順序・色・展開）を満たす
- `/api/chat` と `/api/chat/preview` の双方でタイムライン文脈が利用できる
- 追加テストがすべて成功し、既存テストを壊さない
