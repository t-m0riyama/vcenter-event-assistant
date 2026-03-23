# vCenter Event Assistant（フロントエンド）

[vCenter Event Assistant](../README.md) の Web UI です。React・TypeScript・[Vite](https://vite.dev/) で実装し、バックエンドの FastAPI と同一オリジンまたは開発時プロキシ経由で API を呼び出します。イベントの一覧・概要、ホストメトリクスのグラフ、vCenter 登録やスコアルールなどの設定をブラウザから行えます。

## 画面の例

以下はリポジトリ内のキャプチャ（[`images/`](images/)）です。データ内容は環境により異なります。

### 概要

登録 vCenter 数や直近のイベント件数、スコアの高い要注意イベントの俯瞰を表示します。

![概要タブ](images/summary.png)

### イベント

収集した vCenter イベントを期間・キーワードなどで絞り込み、一覧表示や CSV 出力ができます。

![イベントタブ](images/events.png)

### グラフ（メトリクス）

ホストの CPU・メモリなどの時系列を、vCenter とメトリクス種別を選んで表示します。

![グラフタブ](images/metrics.png)

### 設定（一般）

テーマ（ライト / ダーク / システム）や、日時表示に使うタイムゾーンをブラウザに保存します。

![設定の一般タブ](images/settings-general.png)

### その他の画面・キャプチャの更新

全タブの一覧と PNG の再取得手順は **[開発者向けメモ（`docs/development.md`）](development.md)** を参照してください。リポジトリルートで次を実行すると `docs/images/*.png` を更新できます。

```bash
uv run scripts/capture_ui_screenshots.py
# 既に API が動いている場合（ビルド省略）
uv run scripts/capture_ui_screenshots.py --existing
```

## 開発コマンド

`frontend` ディレクトリで実行します。


| コマンド                  | 説明                                       |
| --------------------- | ---------------------------------------- |
| `npm install`         | 依存関係のインストール                              |
| `npm run dev`         | 開発サーバー（HMR）                              |
| `npm run build`       | 本番用ビルド（`dist/`）                          |
| `npm run test`        | Vitest 単体テスト                             |
| `npm run lint`        | ESLint                                   |
| `npm run e2e`         | ビルド後に Playwright E2E                     |
| `npm run screenshots` | ビルド後にドキュメント用スクリーンショットのみ取得（`docs/images`） |


バックエンドの起動・環境変数は [リポジトリルートの README](../README.md) を参照してください。

## ライセンス

本ディレクトリを含む本プロジェクトは [Apache License 2.0](../LICENSE) に従います。著作権表示は [NOTICE](../NOTICE) を参照してください。

## スタック補足

このディレクトリは `npm create vite@latest` 由来の構成を引き継いでいます。React Compiler の有効化、型対応 ESLint ルールの拡張、Vite の詳細は [Vite 公式ドキュメント](https://vite.dev/guide/) および [React ドキュメント](https://react.dev/) を参照してください。
