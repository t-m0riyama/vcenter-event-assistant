# イベント種別ガイド（公式ドキュメント調査ベース）

## 目的

Broadcom／VMware 公式ドキュメントを根拠に、vCenter が記録する **イベント種別（`event_type`）** ごとに、意味・想定原因・対処・対応要否を **日本語で要約**し、本リポジトリのシード JSON として共有する。アプリのインポート形式は `vea-event-type-guides`（[`eventTypeGuidesFileSchema`](../../frontend/src/api/schemas.ts)）。

## インポート手順

1. アプリの **設定** を開く。
2. **イベント種別ガイド** を選択する。
3. **インポート** で、取り込みたいシード JSON を指定する。
   - **第1弾のみ:** [`data/seed/event-type-guides-priority-v1.json`](../../data/seed/event-type-guides-priority-v1.json)
   - **第2弾の追加:** [`data/seed/event-type-guides-priority-v2.json`](../../data/seed/event-type-guides-priority-v2.json)（第1弾と **別ファイル**。v1 適用済みの DB に **追記だけ** したい場合は、**インポート画面で「ファイルに含まれないガイドを削除」をオフ**のままにする。API の [`EventTypeGuidesImportRequest`](../../src/vcenter_event_assistant/api/schemas.py) および UI の **既定値は `overwrite_existing=true` / `delete_guides_not_in_import=false`** で、追加インポート向きです。）
   - 上書き・削除オプションは運用方針に合わせる。

## 一次情報の取得（イベントカタログ）

vCenter Server は、イベント種別ごとの公式な説明・メッセージ書式・重大度を **イベントカタログ**（`EventManager.description.eventInfo`）として保持している。第2弾シードの本文は、これを一次根拠としている。

```bash
# 登録済み vCenter（DATABASE_URL の DB から取得）に読み取り専用で接続し、日本語カタログを出力する
.venv/bin/python scripts/dump_event_catalog.py --out /tmp/event-catalog-ja.json --locale ja
```

各行は次を持つ。

- `event_type` — シードの `event_type` と突き合わせ可能な型名
- `description` — 公式の短い説明
- `fullFormat` — 実際に記録されるメッセージのテンプレート（参照プロパティ名を含む）
- `longDescription` — `<description>` / `<cause>` / `<action>` を含む詳細説明（**一部の種別のみ**）
- `category` — 公式の重大度（`情報` / `警告` / `エラー` / `ユーザー`）

`--locale ja` を付けると、vCenter が日本語ロケールのメッセージバンドルを持つ場合に日本語で取得できる。

**取得した JSON は環境固有の情報を含みうるため、リポジトリにはコミットしない。**

## 公式情報の要約方針

- **長文の転載は行わない。** 意味・原因・対処は自文で要約する。
- **出典 URL と参照日** は、第1弾が [`citations-priority-v1.md`](./citations-priority-v1.md)、第2弾が [`citations-priority-v2.md`](./citations-priority-v2.md) に記載し、イベント種別ごとに追跡する。
- 製品バージョンやドキュメント改訂が分かる場合は README および出典表に記す。

## 対象 vSphere／ドキュメントの前提

- 第1弾シードの本文は、主に **vSphere 8.x 系の製品ドキュメント**と **vSphere Web Services API リファレンス（例: 7.0 版のデータオブジェクト説明）** を参照して要約している。
- メジャー／マイナーアップ後は、同じ `event_type` でも説明が更新されることがある。**差分確認手順**は後述。

## `action_required`（対応要否）の判断基準（本リポジトリの目安）

第2弾シードでは、**イベントカタログの `category`** を基準に決めている。

- `category = エラー` → 原則 **true**
- `category = 警告` → **個別判断**（放置すると影響が拡大するものは true）
- `category = 情報` / `ユーザー` → 原則 **false**

ただし、`情報` でも **保護の喪失や仮想マシンの強制停止を示すもの**は例外として **true** にしている（`VmDasBeingResetEvent`、`VmPowerOffOnIsolationEvent`、`VmShutdownOnIsolationEvent`、`VmRestartedOnAlternateHostEvent`、`VmSecondaryDisabledEvent`、`NoDatastoresConfiguredEvent` など）。

第1弾シードや手動で追加する種別では、次の目安に従う。

- **true に寄せる:** ホスト切断、ストレージパス喪失、クラスタ／HA の異常、データ損失リスクが高い操作の失敗など、**放置すると影響が拡大しやすい**もの。
- **false に寄せる:** 計画された電源操作・移動・ゲストシャットダウン要求など、**運用上は記録確認で足りる**ことが多いもの。
- 迷う場合は **false** にし、運用チームの定義に合わせて後から更新する（アプリ上も編集可能）。

## 調査の推奨手順

1. アプリや DB に記録された **`event_type` 文字列をそのまま** 検索キーにする（勝手に短縮しない）。
2. **イベントカタログ**（上記 `scripts/dump_event_catalog.py` の出力）で該当種別を引き、`description` / `fullFormat` / `longDescription` / `category` を確認する。**カタログに存在しない種別は、実在しない型名の可能性がある**ため、pyVmomi の型定義と照合する。
3. カタログに `longDescription` がない種別は、Broadcom Developer の **vSphere Web Services API** で `vim.event.<名前>` のデータオブジェクトページを開き、**Data Object Description** とプロパティを確認する。
4. 概念理解が必要なら、TechDocs の **Understanding Events**（Web Services SDK プログラミングガイド）を読む。
5. 本文は要約し、参照 URL と参照日を、対象が第1弾なら [`citations-priority-v1.md`](./citations-priority-v1.md)、第2弾なら [`citations-priority-v2.md`](./citations-priority-v2.md) に追記する。

## レビュー観点

- **用語**（電源オン／オフ、サスペンド、リロケーション等）の統一。
- **`event_type` の表記揺れ**（例: 別名のイベント型が親子関係にある場合は、実際に記録される型名に合わせる）。
- **空欄:** 不明な項目は無理に埋めず `null` に近い扱い（JSON ではキー省略または `null`）とし、出典表に「未確認」と書く。

## マイナーバージョンアップ時の差分確認

- 対象 vSphere の **リリースノート**と **API リファレンスの差分**を確認し、変更があった `event_type` だけシードと出典表を更新する。
- 更新したら **参照日** を新しくする。

## 第2弾（priority v2）への拡張

- シードと出典表を分けて管理する: [`data/seed/event-type-guides-priority-v2.json`](../../data/seed/event-type-guides-priority-v2.json)、[`citations-priority-v2.md`](./citations-priority-v2.md)。実装計画の正本は [`docs/superpowers/plans/2026-03-22-event-type-guides-priority-v2.md`](../superpowers/plans/2026-03-22-event-type-guides-priority-v2.md)。
- **件数:** 現時点 **436 件**。かつて 463 件としていたが、**vSphere API に実在しない型名が 27 件**含まれていたため 2026-09-13 に削除した（経緯は [`citations-priority-v2.md`](./citations-priority-v2.md) を参照）。件数の上限は、対象 vCenter のイベントカタログに現れる `vim.event.*` のうち v1 と重複しないものの総数で決まる。
- 追記作業は **50 件を 1 バッチ**としてまとめる運用を推奨する（大規模一括更新時は例外可。詳細は実装計画）。
- v2 の `event_type` は **v1 シードと重複させない**（追加専用）。v1 に既にある種別の修正が必要なら v1 の JSON を編集する。
- 優先度は [`priority-list-rationale.md`](./priority-list-rationale.md) の **priority v2** 手順で再計算し、バックログ（チケット）に残した `event_type` を順次処理する。

## 関連ファイル

| ファイル | 説明 |
|----------|------|
| [`data/seed/event-type-guides-priority-v1.json`](../../data/seed/event-type-guides-priority-v1.json) | 第1弾インポート用シード（`vea-event-type-guides`） |
| [`data/seed/event-type-guides-priority-v2.json`](../../data/seed/event-type-guides-priority-v2.json) | 第2弾インポート用シード（v1 と重複しない `event_type` のみ。実機の vCenter イベントカタログで実在を確認済み。現時点 **436 件**） |
| [`scripts/dump_event_catalog.py`](../../scripts/dump_event_catalog.py) | vCenter のイベントカタログを JSON に出力する一次情報取得スクリプト（読み取り専用） |
| [`citations-priority-v1.md`](./citations-priority-v1.md) | 第1弾の出典表 |
| [`citations-priority-v2.md`](./citations-priority-v2.md) | 第2弾の出典表 |
| [`priority-list-rationale.md`](./priority-list-rationale.md) | 優先リストの決め方（機微情報はコミットしない） |
