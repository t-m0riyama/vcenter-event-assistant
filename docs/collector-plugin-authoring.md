# コレクタプラグインの開発

vCenter Event Assistant のコレクタプラグインを書くためのガイドです。プラグインは
`vcenter-event-assistant-plugin-api` だけに依存する独立した Python パッケージで、
アプリケーション本体（`vcenter_event_assistant`）を import してはいけません。

運用側の話（設定ファイル、管理画面、動的インストール、ホットリロード、
トラブルシュート）は [コレクタプラグイン](collector-plugins.md) にあります。

---

## 5 分クイックスタート

```bash
# 0. プラグイン API を入れる
pip install vcenter-event-assistant-plugin-api

# 1. ひな形を生成する
python -m vcenter_event_assistant_plugin_api.scaffold my-sensor-collector --kind metric
cd my-sensor-collector

# 2. テストが通ることを確かめる（アプリも vCenter も起動しない）
uv sync
uv run pytest -q

# 3. src/my_sensor_collector/__init__.py の sample() を埋める

# 4. ビルドして管理画面からアップロードする
uv build
```

ここまでで一周します。以降は各ステップの詳細です。

> プラグイン API がまだ PyPI に公開されていない環境では、`uv sync` の代わりに
> リポジトリでビルドした wheel を使ってください
> （`uv build --package vcenter-event-assistant-plugin-api`）。

### スキャフォールド

生成されるのは `pyproject.toml` / `src/<package>/__init__.py` / `tests/test_collector.py` /
`README.md` / `.gitignore` の 5 つです。テストは**最初から通ります**。作者が埋めるのは
`sample()`（または `--kind event` なら `fetch()`）の中身だけです。

| オプション | 既定 | 意味 |
|---|---|---|
| `--kind metric\|event` | `metric` | メトリクスを出すか、イベントを出すか |
| `--id` | 配布名 | `manifest.id` と entry point 名 |
| `--name` | 配布名から生成 | 管理画面に出る表示名 |
| `--out` | `./<配布名>` | 出力先 |
| `--force` | — | 既存ファイルを上書きする |

生成を勧めるのは、書く量が減るからだけではありません。`manifest.id` は
**entry point 名・マニフェスト・メトリクスキーの 3 箇所**に現れ、不一致は
`configured plugin is not installed` という遠い文言になって初めて露見します。生成すれば
一致が保証されます。

手で作る場合は、下の「パッケージの entry point」を参照してください。

## どちらの基底を選ぶか

| | `MetricCollector` | `EventCollector` |
|---|---|---|
| 出すもの | 時系列の数値（CPU 使用率、温度、容量） | 起きた出来事（電源操作、アラーム、監査ログ） |
| 実装するメソッド | `sample(si, context)` | `fetch(si, context, *, since)` |
| 一意性の担保 | `(vcenter_id, sampled_at, entity_moid, metric_key)` | `(vcenter_id, collector_id, vmware_key)` |
| カーソル | 使わない | 基底が管理する（空バッチでも前進する） |
| 事前宣言 | `metrics = (MetricDefinition(...),)` が必須 | 不要 |

どちらも実装するのは**同期のメソッド 1 つ**だけです。両方を出したい場合は、
プラグインを 2 つに分けてください。1 つのコレクタで両方を出すこともできますが、
実行間隔・失敗の切り分け・有効化の単位が分けられなくなります。

## コレクタの書き方

`MetricCollector` または `EventCollector` を継承すると、実装するのは**同期のメソッド 1 つ**
だけになります。マニフェストはクラス属性から組み立てられ、クラス定義の時点で検証されます。

```python
from vcenter_event_assistant_plugin_api import MetricCollector, MetricDefinition, config

TEMPERATURE = MetricDefinition(
    key="example.host.temperature_c",
    display_name="Host temperature",
    unit="C",
    entity_type="HostSystem",
)


class TemperatureCollector(MetricCollector):
    id = "example.host.temperature"
    display_name = "Example Host Temperature"
    version = "0.1.0"
    metrics = (TEMPERATURE,)

    # 同期でよい。基底がスレッドへ逃がし、接続の開閉も行う。
    def sample(self, si, context):
        sensor = config.get_str(context.config, "sensor", "system-board")
        for moid, name in read_hosts(si):
            yield TEMPERATURE.at(
                entity_moid=moid, entity_name=name, value=read_temperature(moid, sensor)
            )


build_collector = TemperatureCollector   # クラス自体が引数なしファクトリになる
```

基底が引き受けるものは次のとおりです。いずれも間違えると静かに壊れる箇所です。

| 基底が持つ | 自分で書くと踏む罠 |
|---|---|
| クラス属性からのマニフェスト生成 | `frozenset({...})` と 1 要素タプルの末尾カンマ |
| `data_kinds` の自動導出 | 書き忘れるとバッチが**丸ごと**拒否される |
| `MOCK_MODE=true` の分岐と既定の合成データ | mock 経路を書き忘れて動かない |
| vCenter 接続の open / close | `async with` の書き忘れ、接続リーク |
| スレッドへの退避 | 素の `asyncio.to_thread` はタイムアウト時にセッションを取り残す |
| 戻り値をスレッド内で確定 | ジェネレータ本体がイベントループ上で回る |
| カーソルの decode / 前進 | 空バッチで前進せず同じ範囲を読み続ける、境界の取りこぼし |

イベントを返す場合は `EventCollector` を継承し、`fetch(si, context, *, since)` を実装します。
`since` は前回のカーソルから 1 秒戻した時刻で（境界のイベントを取りこぼさないため）、
`None` なら初回です。次のカーソルは基底が組み立て、**空のバッチでも必ず前進します**。

`vmware_key` は情報源が持つ**自然キー**を使ってください（詳細は「バッチが拒否される条件」）。

既に `manifest = CollectorManifest(...)` と書いているプラグインは、そのまま基底クラスだけを
使うこともできます。宣言的な書き方へ一度に移行する必要はありません。

## パッケージの entry point

プラグインは `vcenter-event-assistant-plugin-api` のみに依存し、引数なしのファクトリを公開します。

```toml
[project.entry-points."vcenter_event_assistant.collectors"]
temperature = "example_temperature:build_collector"
```

ファクトリは `CollectorPlugin` を実装したオブジェクトを返します。メトリクスキーはマニフェストで
宣言し、インストール済みの全コレクタのあいだで一意である必要があります。各バッチの検証、および
データベース書き込み、イベントスコアリング、重複処理、カーソルのコミットはアプリケーションが
担います。

## ヘルパ

プラグイン API には、どのコレクタでも必要になるヘルパが入っています。

| モジュール | 用途 |
|---|---|
| `validation` | アプリと**同一**の検証規則。`check_batch()` を自分のテストで呼べる（下記参照） |
| `limits` | DB の列長、`vmware_key` の範囲、安定キー生成 |
| `timeutils` | `now_utc()` / `ensure_aware()` / `to_utc()`。naive な datetime はバッチ全体の拒否につながる |
| `blocking` | `run_blocking()`。`asyncio.to_thread` と違い、タイムアウトでキャンセルされてもスレッドと vCenter セッションを取り残さない |
| `logs` | `get_plugin_logger()`。`VEA_COLLECTOR_WORKER_LOG_LEVEL` が効くロガー名を返す |
| `vmware` | pyVmomi でのインベントリ走査。`container_view()` が `Destroy()` を保証する |
| `testing` | アプリを起動せずにコレクタを回すテストハーネス（下記参照） |
| `scaffold` | そのまま動くプラグインのひな形を生成する CLI（上記参照） |

`MetricDefinition.at()` を使うと、メトリクスキーと `entity_type` を宣言から補い、
`sampled_at` に timezone-aware な現在時刻を入れた `MetricSampleInput` を作れます。
宣言とサンプルでキーを二重に書く必要がなくなります。

```python
TEMPERATURE = MetricDefinition(
    key="example.host.temperature_c",
    display_name="Host temperature",
    unit="C",
    entity_type="HostSystem",
)

sample = TEMPERATURE.at(entity_moid="host-1", entity_name="esxi-01", value=31.5)
```

### pyVmomi ヘルパ

`vmware` サブモジュールは、インベントリ走査の定型を引き受けます。型を
**名前の文字列**で受け取るので、プラグイン側で `from pyVmomi import vim` を書く必要は
ありません。

```python
from vcenter_event_assistant_plugin_api import vmware

hosts = vmware.iter_hosts(si)                 # 切断中のホストは既定で除かれる
for host in hosts:
    entity_moid = vmware.moid(host)           # private な `_moId` を直接触らない

with vmware.container_view(si, ["VirtualMachine"]) as vms:
    ...                                       # 抜けるときに必ず Destroy() される
```

`CreateContainerView` は `Destroy()` を呼ばないと vCenter 側にビューが残り続けます。
`container_view()` は例外が出た場合も含めて必ず破棄します。`iter_hosts()` /
`iter_datastores()` も内部でこれを使います。

**pyVmomi の入手について。** このサブモジュールは import された時点では pyVmomi を
読み込まず、関数の中で遅延 import します。コレクタワーカーの `sys.path` にはアプリ本体の
依存として pyVmomi が既に見えているため、プラグイン側は
`vcenter-event-assistant-plugin-api` を extra なしで宣言すれば十分で、オフラインの
`--no-deps` 導入でも動きます。アプリの外でプラグイン単体をテストする場合だけ、
`vcenter-event-assistant-plugin-api[vmware]` を入れてください。

## テストの書き方

`testing` サブモジュールを使うと、**アプリを一度も起動せずに** `pytest` でコレクタを
検証できます。

```python
from vcenter_event_assistant_plugin_api.testing import (
    FakeServiceInstance,
    fake_host,
    run_collect,
)


async def test_samples_every_connected_host():
    si = FakeServiceInstance(
        hosts=[
            fake_host("host-1", "esxi-a"),
            fake_host("host-2", "esxi-b", connected=False),
        ]
    )
    batch = await run_collect(TemperatureCollector(), connection=si)
    assert [sample.entity_moid for sample in batch.metrics] == ["host-1"]


async def test_mock_mode_works():
    batch = await run_collect(TemperatureCollector(), mock_mode=True)
    assert batch.metrics
```

`run_collect()` はアプリが本番で行うことを再現し、さらに手元でしか気づけないことを
検査します。

| `run_collect()` が確かめること | 見逃すとどうなるか |
|---|---|
| `start` → `collect` → `stop` を回す（`collect` が失敗しても `stop` は呼ぶ） | 後片付けが漏れる |
| バッチをアプリと**同一の規則**で検証する | 本番でバッチが丸ごと拒否される |
| warning も既定で失敗させる | 列長超過や重複キーで**データが静かに消える** |
| vCenter 接続の開閉が釣り合っているか | セッションが溜まり続ける |
| `CreateContainerView` のビューが `Destroy()` されたか | ビューが vCenter 側に残り続ける |

主な道具は次のとおりです。

| 名前 | 用途 |
|---|---|
| `run_collect(plugin, ...)` | 上記をまとめて行う。1 行のスモークテスト |
| `make_context(...)` / `make_target(...)` | `CollectionContext` を組み立てる。**既定で動く接続**が入る |
| `FakeServiceInstance` / `fake_host` / `fake_datastore` / `fake_vm` | インベントリを模す |
| `failing_connection(exc)` | `mock_mode=True` が接続を開いていないことを確かめる |
| `assert_batch_valid(manifest, batch)` | バッチだけを個別に検証する |
| `StubCollector` / `stub_manifest()` | 正しく振る舞うコレクタのスタブ |

pytest の fixture（`target` / `service_instance` / `context` / `mock_context`）も
用意していますが、**opt-in** です。`pytest11` の entry point は登録していないので、
使うときは `conftest.py` に次を書いてください。

```python
pytest_plugins = ["vcenter_event_assistant_plugin_api.testing.fixtures"]
```

なお `FakeServiceInstance` を `vmware` ヘルパ経由で使う場合は、型名の解決に pyVmomi が
必要です（`vcenter-event-assistant-plugin-api[vmware]`）。ハーネス本体は pytest にも
pyVmomi にも依存していません。

## 落とし穴チェックリスト

いずれも**本番で静かに壊れる**ものです。「基底を使えば踏まない」ものと、
「手元で検出する方法」を併記しています。

| 落とし穴 | 何が起きるか | 対処 |
|---|---|---|
| timezone-naive な datetime | バッチが**丸ごと**拒否される | `MetricDefinition.at()` が自動で付ける。手で作るなら `timeutils.ensure_aware()`。`run_collect()` が検出 |
| `data_kinds` の書き忘れ | 全バッチが拒否される | 基底クラスが導出するので書かない |
| 宣言していないメトリクスキー | バッチが丸ごと拒否される | `at()` が定義からキーを補う。`run_collect()` が検出 |
| `NaN` / `inf` | バッチが丸ごと拒否される | `run_collect()` が検出 |
| `vmware_key` をハッシュで作る | 重複排除が `ON CONFLICT DO NOTHING` なので、衝突したイベントが**エラーもログもなく消える**（31 bit では約 4.6 万件で 50%） | 情報源の**自然キー**を使う。`limits.stable_int31()` は推奨しない |
| `vmware_key` が 2^31 を超える | DB で失敗する | `limits.VMWARE_KEY_MIN/MAX` で確認。`check_batch()` が warning を出す |
| `entity_name` などが列長を超える | DB で失敗する | `limits.truncate()` で収める。`run_collect()` が検出 |
| バッチ内で重複排除キーが衝突 | DB では 1 件しか残らない（**静かに消える**） | `run_collect()` が warning として検出 |
| 環境変数由来の設定値が `str` | 管理画面から設定したときだけ壊れる | `config.get_int()` などを通す |
| 素の `asyncio.to_thread` | タイムアウト時にスレッドと vCenter セッションが残る | 基底が `run_blocking()` を使う。自分で書くなら同じものを使う |
| `view.Destroy()` の呼び忘れ | ビューが vCenter 側に残り続ける | `vmware.container_view()` / `iter_hosts()` を使う。`run_collect()` が検出 |
| `print()` を使う | **stdout はワーカーのプロトコル専用**なので、混ざると全プラグインの通信が壊れる | `get_plugin_logger()` を使う（出力は stderr） |
| カーソルを前進させない | 同じ範囲を永久に読み直す | `EventCollector` が空バッチでも前進させる |
| 取得範囲の開始を戻さない | 境界上のイベントを取りこぼす | `TimestampCursor` が既定で 1 秒戻す |
| 機密を TOML や DB に置く | 設定ファイルや DB のバックアップに残る | プラグインが所有する環境変数から読む |
| entry point 名と `manifest.id` の不一致 | `configured plugin is not installed` として `failed` になる | スキャフォールドが一致を保証する |

`check_batch(manifest, batch)` を自分のテストや開発中の `collect()` の末尾で呼べば、
error も warning も**本番で潰される前に**理由付きで分かります。`run_collect()` は
これを既定で行い、warning でも失敗します。

## バッチが拒否される条件

アプリは各バッチを検証し、違反があれば**丸ごと**拒否します。部分保存もカーソル前進も
起こらないため、1 件の不正で収集全体が失敗します。

| 条件 | `error_message` |
|---|---|
| `data_kinds` に `event` が無いのにイベントを返した | `collector emitted undeclared event data` |
| `data_kinds` に `metric` が無いのにメトリクスを返した | `collector emitted undeclared metric data` |
| manifest で宣言していないメトリクスキー | `undeclared metric key: <キー>` |
| `NaN` / `inf` | `non-finite metric value: <キー>` |
| `sampled_at` が timezone-naive | `metric sampled_at must be timezone-aware` |
| `occurred_at` が timezone-naive | `event occurred_at must be timezone-aware` |

**同じ判定を手元で実行できます。** 規則は `vcenter-event-assistant-plugin-api` の
`validation` モジュールにあり、アプリはそれを呼んでいるだけです。

```python
from vcenter_event_assistant_plugin_api.validation import check_batch

for issue in check_batch(collector.manifest, batch):
    print(issue.severity, issue.code, issue.message, issue.index)
```

`check_batch` は、アプリが拒否しない**警告**も返します。いずれも放置すると
**エラーもログもなくデータが失われる**ものです。

| 警告 | 何が起きるか |
|---|---|
| `field_too_long` | DB の列長を超過。収集時に DB エラーになる（列長は `limits` モジュールで公開） |
| `duplicate_dedup_key` | 重複排除キーがバッチ内で衝突。`ON CONFLICT DO NOTHING` により 1 件だけ残り、残りは黙って捨てられる |
| `vmware_key_out_of_int32_range` | `vmware_key` は `Integer` 列。PostgreSQL では失敗する（SQLite では通るので気づきにくい） |
| `empty_entity_moid` | `entity_moid` はメトリクスの重複排除キーの一部 |
| `unused_metric_definitions` | メトリクスを宣言しているが `data_kinds` に `metric` が無い |

`vmware_key` は**情報源が持つ自然キー**（vCenter の `Event.key` など）を使ってください。
ハッシュを 31 bit に押し込むと、約 4.6 万件で 50% の確率で誕生日衝突が起き、衝突した
イベントが静かに消えます。

## 開発ループ

```bash
uv run pytest -q          # まずここで落とす（アプリ不要）
uv build                  # wheel を作る
# 管理画面からアップロード → 反映 → 有効化 → 反映
```

外部プラグインは既定で無効です。アップロードしただけでは動きません。

### ログの見方

プラグインのログはコレクタワーカーの **stderr** に出ます。アプリのプロセスに継承される
ので、アプリを起動した端末（または systemd のジャーナル）で見られます。

```bash
VEA_COLLECTOR_WORKER_LOG_LEVEL=DEBUG uv run vcenter-event-assistant
```

この設定は**外部プラグインだけ**をログレベルの対象にします。アプリ全体を DEBUG に
する必要はありません。`get_plugin_logger()` が返すロガー名がこの設定に対応しています。

### 失敗の読み方

管理画面と `GET /api/plugins/collectors` の `error_message` には、**安全だと分かって
いる型**のメッセージだけが出ます（`ImportError`、`NotImplementedError`、
検証エラー、マニフェストエラー）。それ以外は型名だけです。例外文言には認証情報や
サーバ応答が混ざりうるためです。

詳細は必ずワーカーの stderr にあります。読み方は
[コレクタプラグインのトラブルシュート](collector-plugins.md#トラブルシュート)を参照してください。

## 配布とバージョニング

プラグインは extra なしで plugin-api を宣言します。

```toml
[project]
dependencies = ["vcenter-event-assistant-plugin-api>=1.1,<2"]

[dependency-groups]
dev = [
    "pytest", "pytest-asyncio",
    # `vmware` ヘルパをアプリの外で動かすときだけ必要
    "vcenter-event-assistant-plugin-api[vmware]>=1.1,<2",
]
```

pyVmomi は**実行時にはアプリ本体の依存としてワーカーの `sys.path` に見えている**ので、
プラグイン側でインストールする必要はありません。これはオフラインの
`--no-index --no-deps` インストールでも動くことを意味します。extra が要るのは、
アプリの外でプラグイン単体をテストするときだけです。

### 2 つのバージョンを混同しないこと

| | 意味 | 上げるとき |
|---|---|---|
| `__version__` | plugin-api パッケージの SemVer | 後方互換な追加で minor |
| `PLUGIN_API_VERSION` | 契約世代。アプリが `manifest.api_version` と突き合わせる | **契約を壊すときだけ** |

アプリは `api_version` が一致しないプラグインを
`unsupported plugin API version` として `failed` にします。`PLUGIN_API_VERSION` を
上げると、**既存の全プラグインが一斉に動かなくなります**。

プラグインが宣言すべき範囲は `>=<使っている minor>,<2` です。上限を付けないと、
契約が変わる major で壊れます。

## サンプルプラグイン

[`examples/example-temperature-collector/`](../examples/example-temperature-collector/) は実行可能な
サンプルです。最小構成のメトリクスコレクタと、ビルド・インストール・有効化・リロード・
アンインストールを網羅した README で構成されます。障害を注入することもできるため
(`EXAMPLE_COLLECTOR_FAULT=hang|crash|raise`)、後述のプロセス分離の挙動を端から端まで観察できます。
このパッケージは意図的に uv ワークスペースのメンバーに含めていないため、開発環境に誤って
インストールされることはありません。

[`examples/example-event-collector/`](../examples/example-event-collector/) はイベント側の
サンプルです。**イベント側はメトリクス側より罠が多い**ため（カーソルの前進、`vmware_key` の
一意性と 2^31 の上限、列長）、正解の形を別に置いています。

どちらのサンプルも、アプリを起動せずに `pytest` だけでテストが通ります。

```bash
uv run pytest examples/example-temperature-collector/tests examples/example-event-collector/tests -q
```

