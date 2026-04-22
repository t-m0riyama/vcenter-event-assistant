# vCenter HTTP Proxy サポート — デザインドキュメント

## 概要

環境変数 `VCENTER_HTTP_PROXY`（URL 形式、例: `http://proxy.example.com:8080`）で HTTP プロキシを指定し、
すべての vCenter 接続（イベント取得・メトリクス収集・接続テスト）をプロキシ経由にする。

## 設計方針

- **グローバル設定**: 1 つのプロキシ URL をすべての vCenter 接続に適用
- **環境変数 URL 形式**: `VCENTER_HTTP_PROXY=http://proxy:8080`（`urllib.parse.urlparse` でホスト・ポート分離）
- **pyVmomi ネイティブ対応**: `SmartConnect` の既存パラメータ `httpProxyHost` / `httpProxyPort` を利用
- **未設定時**: プロキシなし（現状と同じ動作を維持）

## 変更箇所

1. `settings.py` — `vcenter_http_proxy` フィールド追加 + バリデータ
2. `collectors/connection.py` — `connect_vcenter()` にプロキシ引数追加・URL パース
3. `collectors/events.py` — `fetch_events_blocking()` にプロキシ引数追加
4. `collectors/perf.py` — `sample_hosts_blocking()` にプロキシ引数追加
5. `api/routes/vcenters.py` — 接続テストでプロキシ設定を渡す
6. `services/ingestion.py` — イベント・メトリクス取得でプロキシ設定を渡す
7. `.env.example` — 設定例追記
8. テスト — 設定パース・接続関数へのプロキシ引数受け渡し
