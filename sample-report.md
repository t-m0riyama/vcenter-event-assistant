# インシデントタイムライン 調査資料（2026/11/24 06:31:48 +09:00 ～ 2026/11/24 07:31:48 +09:00）

- 出力した時刻: 2026/11/24 07:31:54 +09:00
- 出典: 今の表示（集計した時刻: 2026/11/24 07:31:54 +09:00）
- 表示の後に集計し直したので、画面と件数が違うことがある

上限付きの要約です。サポートバンドルの代わりにはなりません。

## 条件

- 期間: 2026/11/24 06:31:48 +09:00 ～ 2026/11/24 07:31:48 +09:00
- 起点: -
- vCenter: すべて
- 対象（部分一致）: -
- 対象の moid: -
- 種別: ` event `、` alert `、` metric `、` log `
- min_score: 1
- メトリクスのしきい値: CPU 80%、メモリ 85%

## 概要

- 出来事: 11 件 / 総数 11 件
- 打ち切り: なし
- 省いた種別: -
- 種類ごとの件数: イベント 6 件、アラート 1 件、メトリクス 2 件、ログ 2 件

## ハイライト

### 最初の兆候

- 2026/11/24 06:37:45 +09:00 / イベント / warning / ` demo-esxi-01 ` / ` vim.event.HostConnectionLostEvent ` / ` （デモ）ホストと vCenter の接続が切れました `

### 影響の大きい対象（上位）

- ` demo-esxi-01 ` / ` screenshot-e2e-vc ` / 6 件 / 2026/11/24 06:37:45 +09:00
- ` demo-vm-01 ` / ` screenshot-e2e-vc ` / 2 件 / 2026/11/24 06:45:45 +09:00
- ` demo-vm-02 ` / ` screenshot-e2e-vc ` / 2 件 / 2026/11/24 06:49:45 +09:00
- ` demo-esxi-02 ` / ` screenshot-e2e-vc ` / 2 件 / 2026/11/24 06:55:45 +09:00
- ` demo-vm-03 ` / ` screenshot-e2e-vc ` / 1 件 / 2026/11/24 07:31:45 +09:00

### 初めて出た種別

- ` vim.event.ScreenshotDemoEventC ` / 1 件 / 2026/11/24 06:58:45 +09:00 / 最大スコア 85
- ` vim.event.ScreenshotDemoEventB ` / 2 件 / 2026/11/24 06:45:45 +09:00 / 最大スコア 60
- ` vim.event.HostConnectionLostEvent ` / 3 件 / 2026/11/24 06:37:45 +09:00 / 最大スコア 40
- ` vim.event.ScreenshotDemoEvent ` / 3 件 / 2026/11/24 06:49:45 +09:00 / 最大スコア 10

### 検知した障害パターン

- ` ホストの切断の繰り返し ` / ` demo-esxi-01 ` / 2026/11/24 06:37:45 +09:00 ～ 2026/11/24 06:43:45 +09:00 / 3 件 / ` 同じホストと vCenter の接続が短時間に繰り返し切れています。まず管理ネットワークの疎通とホストの管理エージェントの状態を確認してください。 `
- 判定を省いたパターン: -

## 注目すべき出来事

全 11 件のうち 11 件。全件は ZIP の出力にある

| 時刻 | 種類 | レベル | vCenter | 対象 | 表題 | 詳細 | 件数 | スコア |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026/11/24 06:37:45 +09:00 | イベント | warning | ` screenshot-e2e-vc ` | ` demo-esxi-01 ` | ` vim.event.HostConnectionLostEvent ` | ` （デモ）ホストと vCenter の接続が切れました ` | 3 | 40 |
| 2026/11/24 06:45:45 +09:00 | イベント | error | ` screenshot-e2e-vc ` | ` demo-vm-01 ` | ` vim.event.ScreenshotDemoEventB ` | ` （デモ）仮想マシンの状態が変わりました ` | 1 | 60 |
| 2026/11/24 06:49:45 +09:00 | イベント | info | ` screenshot-e2e-vc ` | ` demo-vm-02 ` | ` vim.event.ScreenshotDemoEvent ` | ` （デモ）通常の操作です ` | 2 | 5 |
| 2026/11/24 06:51:45 +09:00 | ログ | warning | ` screenshot-e2e-vc ` | ` demo-esxi-01 ` | ` demo-esxi-01 vmkernel ` | ` （デモ）ストレージへの応答が遅れています ` | 3 | - |
| 2026/11/24 06:55:45 +09:00 | メトリクス | warning | ` screenshot-e2e-vc ` | ` demo-esxi-02 ` | ` メモリ使用率が閾値（85%）を超過 ` | ` ピーク 94%、サンプル 4 件 ` | 1 | - |
| 2026/11/24 06:58:45 +09:00 | イベント | critical | ` screenshot-e2e-vc ` | ` demo-esxi-01 ` | ` vim.event.ScreenshotDemoEventC ` | ` （デモ）ホストで要確認の事象が起きました ` | 1 | 85 |
| 2026/11/24 07:01:45 +09:00 | メトリクス | warning | ` screenshot-e2e-vc ` | ` demo-esxi-01 ` | ` CPU 使用率が閾値（80%）を超過 ` | ` ピーク 92%、サンプル 4 件 ` | 1 | - |
| 2026/11/24 07:03:45 +09:00 | ログ | error | ` screenshot-e2e-vc ` | ` demo-esxi-02 ` | ` demo-esxi-02 hostd ` | ` （デモ）管理サービスが応答しません ` | 1 | - |
| 2026/11/24 07:16:45 +09:00 | イベント | warning | ` screenshot-e2e-vc ` | ` demo-vm-01 ` | ` vim.event.ScreenshotDemoEventB ` | ` （デモ）仮想マシンの状態が再び変わりました ` | 1 | 30 |
| 2026/11/24 07:31:45 +09:00 | アラート | warning | - | - | ` デモ: イベントスコア が発火 ` | ` イベント種別: vim.event.ScreenshotDemoEvent ` | 1 | - |
| 2026/11/24 07:31:45 +09:00 | イベント | info | ` screenshot-e2e-vc ` | ` demo-vm-03 ` | ` vim.event.ScreenshotDemoEvent ` | ` （デモ）スクリーンショット用イベント ` | 1 | 10 |
