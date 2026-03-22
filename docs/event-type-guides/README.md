# イベント種別ガイド（公式ドキュメント調査ベース）

## 目的

Broadcom／VMware 公式ドキュメントを根拠に、vCenter が記録する **イベント種別（`event_type`）** ごとに、意味・想定原因・対処・対応要否を **日本語で要約**し、本リポジトリのシード JSON として共有する。アプリのインポート形式は `vea-event-type-guides`（[`eventTypeGuidesFileSchema`](../../frontend/src/api/schemas.ts)）。

## インポート手順

1. アプリの **設定** を開く。
2. **イベント種別ガイド** を選択する。
3. **インポート** で、このリポジトリの [`data/seed/event-type-guides-priority-v1.json`](../../data/seed/event-type-guides-priority-v1.json) を指定する（上書き・削除オプションは運用方針に合わせる）。

## 公式情報の要約方針

- **長文の転載は行わない。** 意味・原因・対処は自文で要約する。
- **出典 URL と参照日** は [`citations-priority-v1.md`](./citations-priority-v1.md) に記載し、イベント種別ごとに追跡する。
- 製品バージョンやドキュメント改訂が分かる場合は README および各シードの前提説明に記す（後続タスクで拡張）。

## 関連ファイル

| ファイル | 説明 |
|----------|------|
| [`data/seed/event-type-guides-priority-v1.json`](../../data/seed/event-type-guides-priority-v1.json) | インポート用シード（`vea-event-type-guides`） |
| [`citations-priority-v1.md`](./citations-priority-v1.md) | 出典表 |
| [`priority-list-rationale.md`](./priority-list-rationale.md) | 優先リストの決め方（機微情報はコミットしない） |
