# example-temperature-collector

vCenter Event Assistant のコレクタプラグインのサンプルである。ESXi ホストごとに合成の温度
メトリクス（`example.host.temperature_c`）を 1 点返す。

用途は 2 つある。

- **プラグインを書くときの雛形**: entry point の宣言、`CollectorManifest`、`collect()` の実装、
  `open_vcenter_connection()` の使い方、ブロッキング処理の逃がし方を最小構成で示す。
- **動作確認**: 動的インストール・ホットリロード・プロセス分離が実際に効いているかを確かめる。

本体のドキュメントは [`docs/collector-plugins.md`](../../docs/collector-plugins.md) を参照する。

> このパッケージは uv ワークスペースのメンバーに**含めていない**。含めると開発環境の venv に
> 常時インストールされ、通常の開発中にも検出ワーカーが起動してしまうためである。
> 使うときは下記のとおり明示的にビルドしてインストールする。

## ビルド

```bash
uv build --project examples/example-temperature-collector --out-dir dist/examples
```

`dist/examples/example_temperature_collector-0.1.0-py3-none-any.whl` ができる。

## インストールと有効化

アプリをプラグイン管理有効で起動する。

```bash
DATABASE_URL="sqlite+aiosqlite:////tmp/vea-check.db" \
MOCK_MODE=true VEA_PLUGIN_MANAGEMENT_ENABLED=true \
VEA_PLUGIN_DIR=/tmp/vea-plugins UVICORN_PORT=8099 \
uv run vcenter-event-assistant
```

**Settings > プラグイン**から wheel をアップロードするか、API を直接叩く。

```bash
B=http://127.0.0.1:8099
curl -s -X POST $B/api/plugins/installed/upload \
  -F "file=@dist/examples/example_temperature_collector-0.1.0-py3-none-any.whl"

# インストール完了を待つ
sleep 6 && curl -s $B/api/plugins/installed

# 反映（外部プラグインは既定で無効なので、この時点では disabled で登録される）
curl -s -X POST $B/api/plugins/collectors/reload -d '{}' -H 'Content-Type: application/json'

# 有効化して再度反映
curl -s -X PATCH $B/api/plugins/collectors/example.host.temperature \
  -d '{"enabled":true,"interval_seconds":60}' -H 'Content-Type: application/json'
curl -s -X POST $B/api/plugins/collectors/reload -d '{}' -H 'Content-Type: application/json'
```

60 秒ほど待つと収集が走る。**この間アプリを一度も再起動していない**ことが要点である。

```bash
sqlite3 /tmp/vea-check.db \
  "select collector_id, status, metrics_inserted from collector_run_states;"
sqlite3 /tmp/vea-check.db \
  "select entity_name, metric_key, value from metric_samples
   where collector_id='example.host.temperature' limit 5;"
```

## 障害注入によるプロセス分離の確認

`EXAMPLE_COLLECTOR_FAULT` を設定してアプリを起動すると、`collect()` が意図的に失敗する。
**確認用の仕掛けであり、通常運用では設定しない。**

| 値 | 挙動 | 期待される結果 |
|---|---|---|
| `hang` | 応答しない | `timeout_seconds` 経過でワーカーが kill され、`collector_run_states` が `failed`。アプリは応答し続ける |
| `crash` | ワーカープロセスを即死させる | `failed` として記録され、次回実行で新しいワーカーが起動して復帰する |
| `raise` | 例外を送出する | `failed` として記録され、例外の詳細（メッセージ本文）はアプリの外に出ない |

いずれの場合も `/health` が正常を返し続け、他のコレクタが影響を受けないことを確認する。

```bash
EXAMPLE_COLLECTOR_FAULT=hang \
DATABASE_URL="sqlite+aiosqlite:////tmp/vea-check.db" \
MOCK_MODE=true VEA_PLUGIN_MANAGEMENT_ENABLED=true \
VEA_PLUGIN_DIR=/tmp/vea-plugins UVICORN_PORT=8099 \
uv run vcenter-event-assistant
```

`timeout_seconds` を短く（例: 20 秒）しておくと待ち時間が短くて済む。

```bash
curl -s -X PATCH $B/api/plugins/collectors/example.host.temperature \
  -d '{"timeout_seconds":20}' -H 'Content-Type: application/json'
```

## アンインストール

```bash
curl -s -X DELETE $B/api/plugins/installed/example-temperature-collector
curl -s -X POST $B/api/plugins/collectors/reload -d '{}' -H 'Content-Type: application/json'
```

## プラグインを書くときの注意

- 依存は `vcenter-event-assistant-plugin-api` だけにする。アプリ本体を import してはならない。
- `manifest.id` とメトリクスキーは、インストール済みの全コレクタで一意にする。衝突すると
  レジストリが `failed` として弾く。
- vCenter へは `context.open_vcenter_connection()` 経由でのみ触れる。接続の確立と切断は
  アプリ側が行うため、プラグインは認証情報を受け取らない。
- 機密値は、そのプラグインが所有・文書化した環境変数から読む。TOML や DB には置かない。
- pyVmomi のような同期 API は `asyncio.to_thread` に逃がす。イベントループを止めると、
  同じワーカープロセス上の他の処理まで巻き添えになる。
- オフラインのアップロードでは依存パッケージは導入されない（`--no-index --no-deps`）。
  `vcenter-event-assistant-plugin-api` 以外の依存が必要なら、インデックス経由での
  インストールを有効にするか、依存を同梱すること。不足している場合はインストール直後の
  検証で `ModuleNotFoundError` となり、ディレクトリごとロールバックされる。
