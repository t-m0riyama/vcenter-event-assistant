# example-event-collector

vCenter Event Assistant の**イベント**コレクタプラグインのサンプルである。仮想マシンの
電源操作イベント（`VmPoweredOnEvent` など）だけを取り込む。

メトリクス側のサンプルは
[`examples/example-temperature-collector`](../example-temperature-collector) にある。
**イベント側はメトリクス側より罠が多い**ため、正解の形を別に置いてある。

> このパッケージは uv ワークスペースのメンバーに**含めていない**。含めると開発環境の venv に
> 常時インストールされ、通常の開発中にも検出ワーカーが起動してしまうためである。

## テスト

アプリも vCenter も起動せずに、`pytest` だけで確認できる。

```bash
uv run pytest examples/example-event-collector/tests -q
```

`tests/test_power_event_collector.py` は `plugin_api.testing` のハーネスを使っている。

```python
si = FakeServiceInstance(events=[fake_event(101, event_type="VmPoweredOnEvent")])
batch = await run_collect(PowerEventCollector(), connection=si)
assert [event.vmware_key for event in batch.events] == [101]
```

`run_collect()` は `start` → `collect` → `stop` を回したうえで、バッチをアプリと同一の
規則で検証し（warning でも落ちる）、vCenter 接続のリークと `CreateCollectorForEvents` の
`DestroyCollector()` 漏れも検査する。

## 実装するところ

`fetch()` だけである。カーソル・接続・スレッド退避・`CollectionBatch` の組み立ては
`EventCollector` が引き受ける。

## イベント側で踏みやすい罠

| 罠 | 何が起きるか | このサンプルでの対処 |
|---|---|---|
| `vmware_key` をハッシュで作る | 重複排除は `ON CONFLICT DO NOTHING` なので、衝突したイベントが**エラーもログもなく消える**。31 bit 空間では約 4.6 万件で 50% の確率で衝突する | vCenter が振る `Event.key`（自然キー）をそのまま使う |
| `key` の無いイベントを `0` に潰す | 重複排除で 1 件しか残らない | 警告を出してスキップする |
| `vmware_key` が 2^31 を超える | `EventRecord.vmware_key` は `Integer` なので DB で失敗する | `limits.VMWARE_KEY_MIN/MAX` で範囲を確認する |
| カーソルを前進させない | 同じ範囲を永久に読み直す | 基底が**空のバッチでも**前進させる |
| 取得範囲の開始を戻さない | 境界上のイベントを取りこぼす | `TimestampCursor` が既定で 1 秒戻す（再読分は重複排除で落ちる） |
| naive な datetime | バッチが**丸ごと**拒否される | `timeutils.ensure_aware()` を通す |
| `entity_name` が列長を超える | DB で失敗する | `limits.truncate()` で収める |
| ページングに上限が無い | 長期停止からの復帰で 1 回の収集が終わらない | `MAX_PAGES` で打ち切り、警告を出す |

## ビルドとインストール

```bash
uv build --project examples/example-event-collector --out-dir dist/examples
```

**Settings > プラグイン**から wheel をアップロードし、反映・有効化する。外部プラグインは
既定で無効なので、アップロード後に有効化が必要である。手順の詳細は
[`examples/example-temperature-collector/README.md`](../example-temperature-collector/README.md)
と [`docs/collector-plugins.md`](../../docs/collector-plugins.md) を参照する。

## 設定

| キー | 既定 | 意味 |
|---|---|---|
| `event_types` | `VmPoweredOnEvent,VmPoweredOffEvent,VmSuspendedEvent` | 取り込むイベント種別。カンマ区切り |

`VEA_COLLECTOR__EXAMPLE_VCENTER_POWER_EVENTS__EVENT_TYPES` のような環境変数、
`collectors.toml`、管理画面のいずれからでも設定できる。環境変数由来の値は常に `str` に
なるため、実装では `config.get_str_list()` を通して読んでいる。
