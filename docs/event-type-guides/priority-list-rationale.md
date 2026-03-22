# 優先リスト（priority v1）の決め方

本ファイルは **機微情報（vCenter の URL、トークン、顧客名、環境固有のイベント一覧のダンプ）をコミットしない** ことを前提とする。実データはローカルまたは社内チケットに保持し、ここには **手順と判断基準** のみを書く。

## 1. 収集済みイベント DB からの抽出

1. アプリ API（認証済み）で `GET /api/event-types?limit=500` を呼び、**最近発生が多い種別**を取得する。
2. ダッシュボード要約（例: `GET /api/dashboard/summary`）の **イベント種別トップ** と突き合わせ、重複をまとめる。
3. 得られた `event_type` をメモし、第1弾に含めるかチームで優先度付けする（数十件目安）。

**注意:** 取得結果そのもの（長大な JSON）をこのリポジトリに貼らない。

## 2. 定番カテゴリでの補完

DB にまだ現れていなくても、障害調査で頻出する次のような **カテゴリ** から代表的な `event_type` を追加する:

- 仮想マシンの電源・ライフサイクル（起動／停止／作成 等）
- vMotion／Storage vMotion
- ストレージ接続・パス選択
- HA／FDM
- ネットワーク／分散スイッチ

補完した場合は **なぜその種別を入れたか** を1文で書く（下表）。

## 3. 第1弾に含める候補（手動で追記）

| event_type | 採用理由（1文） |
|------------|-----------------|
| （ローカルで決めた一覧を貼る） | |

## 4. 次のステップ

優先リストが固まったら [`../../data/seed/event-type-guides-priority-v1.json`](../../data/seed/event-type-guides-priority-v1.json) にガイド本文を追加し、[`citations-priority-v1.md`](./citations-priority-v1.md) に出典を1行以上ずつ追加する。

## 5. priority v2（第2弾）の優先リスト

第1弾（priority v1）に **含めなかった**、または **後から優先度が上がった** `event_type` を、第2弾用シード [`../../data/seed/event-type-guides-priority-v2.json`](../../data/seed/event-type-guides-priority-v2.json) と出典表 [`citations-priority-v2.md`](./citations-priority-v2.md) に載せる。手順の骨子はセクション 1〜2 と同じである。

1. **収集済みイベント DB との突合せ:** `GET /api/event-types?limit=500` および `GET /api/dashboard/summary` のイベント種別上位などから、まだガイドがない `event_type` を列挙する（結果の生データはリポジトリに貼らない）。
2. **定番カテゴリの補完:** セクション 2 と同様に、障害調査で頻出するカテゴリから候補を足す。
3. **v1 との差分:** 既に v1 シードに存在する `event_type` は **v2 に含めない**（重複回避）。その種別の修正が必要なら v1 の JSON／`citations-priority-v1.md` を更新する。
4. **バックログ運用:** 数百件規模を想定し、チケットまたはローカルメモで `event_type` を順次処理する。優先度の付け方はチーム合意に従う。

詳細な作業分割は [`../superpowers/plans/2026-03-22-event-type-guides-priority-v2.md`](../superpowers/plans/2026-03-22-event-type-guides-priority-v2.md) を参照する。
