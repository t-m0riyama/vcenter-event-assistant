# ログのパターン集約

最終更新: 2026-11-25（PR C レビュー中）

[障害調査を楽にする機能 10 案](2026-11-22-troubleshooting-ideas.md)（以下「10 案」）の「案 8」にあたる。リモートログを、数値や ID を伏せた「型」でまとめ、型ごとの件数と、初めて出た型を見せる。Issue は起票していない。

コードの場所は、バックエンドを `src/vcenter_event_assistant/` から、画面を `frontend/src/` から書く。行番号は、本書を書いた時点の origin/main（fc3d73f）のものである。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| A | 本書 | 完了（PR #377） |
| B | 型の付与と台帳（取り込み・移行・埋め戻し・削除） | 完了（PR #378） |
| C | API（ログの型ごとの集計、タイムラインの初出の型、出力） | レビュー中 |
| D | 画面（ログタブの型ごとの表示、タイムラインのカード）と文書 | 未着手 |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

リモートログ（ESXi の vmkernel・hostd・vpxa、vCenter の vpxd）は、1 時間に数千行になることがある。障害の調査では、「いつもと違うログが出ていないか」を知りたい。しかし今は、ログタブで 1 行ずつ読むか、文字列で検索するしかない。同じ内容の行が数値や ID だけ違って大量に並ぶので、珍しい行が埋もれる。

決めたこと（利用者の決定）:
- **表示場所:** ログタブに「型ごと」の表示を足す。タイムラインのハイライトに「初めて出たログの型」のカードを足す。
- **初出の基準:** 型の台帳（型ごとに初めて見た時刻を持つ表）を作り、ログの保持期間（7 日）より長く残す。「この環境で初めて出た型」が分かるようにする。
- **重大度:** 型は、取り込むすべてのログに付ける。タイムラインの「初めて出た型」には、warning 以上の行を持つ型だけを出す。
- **型の作り方:** 決めた規則（正規表現）で、時刻・数値・ID などを伏せる。自動のクラスタリング（Drain など）は使わない。結果が取り込みの順に左右されず、説明できるようにするためである。

10 案の計画書の注意を引き継ぐ。型はログの要約であり、ログの代わりにはならない。伏せ方の規則は完全ではなく、同じ内容が別の型に分かれたり、違う内容が同じ型にまとまったりすることがある。

## 1. 前提（コードで確かめたこと）

- **ログの表:** `log_records`（`db/models.py:208`、モデル `LogRecord`）。
  - 列は、`vcenter_id`・`collector_id`・`source_id`・`host`・`log_kind`・`file_generation`・`byte_offset`・`occurred_at`・`collected_at`・`effective_at`（`occurred_at` が無ければ `collected_at`）・`severity`・`message`。
  - 一意制約は `(vcenter_id, collector_id, source_id, log_kind, file_generation, byte_offset)`。
  - 索引:
    - `(vcenter_id, effective_at, id)`、`(effective_at, id)`
    - 単一の列の `source_id`・`log_kind`・`effective_at`
    - 式の索引 `(lower(trim(severity)), effective_at)` と `(vcenter_id, lower(trim(severity)), effective_at)`（233-246 行）
- **ログが入る経路:**
  - プラグインのバッチを `plugins/runtime.py` の `_persist_batch` が 1 行ずつ `ON CONFLICT DO NOTHING` で入れる（259-271 行）。ログの件数は `rowcount` で数えている。1 バッチは 1 トランザクションで、ロックは（プラグイン、vCenter）ごとである。
  - スクリーンショット用のシード（`dev/screenshot_e2e_seed.py:290`）が `LogRecord` を直接入れる。
  - 旧経路の `services/ingestion.py` と、モックの収集（`mocks/mock_collectors.py`、`plugins/builtin.py`）はログを入れない。
- **リモートログ収集**（`packages/remote-log-collector/`）:
  - 収集するのは、ESXi の `vmkernel`・`hostd`・`vpxa` と、vCenter の `vpxd`（`config.py:10-12`）。
  - 時刻で始まる行から次の時刻の行の前までを 1 件にする。複数行の記録がある（`parser.py` の `records`）。`message` は時刻を含む本文そのものである。
  - 重大度は、1 行目に現れる `panic|critical|error|warning|warn|info|debug|verbose` の語から取る（`warn` は `warning` にする）。見つからなければ None になる。ESXi 7 以降の `In(166)`・`Wa(164)` のような形には対応していない。
  - プラグインの時刻は UTC に直さずに入ることがある（`plugins/wire.py` の `_dt_from_json`）。SQLite では時刻を文字列で比べる。
  - 本文の長さに上限は無い（plugin-api の検証は `message` を見ない）。
- **ログの重大度の扱い:** タイムラインは `lower(trim(severity))` で揃え、`_LOG_LEVEL_BY_SEVERITY`（`services/incident_timeline_view.py:136`）で `error`・`err`・`critical`・`crit`・`fatal`・`panic`・`alert`・`emerg` を扱う。一覧に出すのは、これらの行だけである（`_log_filters`、1815 行。期間は `[from, to)`、対象の絞り込みは `host` に当て、moid だけの指定では空になる）。
- **削除:** `purge_old_logs`（`services/ingestion.py:360`）が、`effective_at` が `LOG_RETENTION_DAYS`（既定 7 日、`settings.py:79`）より古い行を消す。定期ジョブ（`jobs/scheduler.py:121`）から呼ばれる。
- **ログの API**（`api/routes/logs.py`）: `GET /api/logs` は、vCenter・`source_id`・`log_kind`・`severity`・本文の部分一致・期間で絞る（`log_conditions`、29 行）。期間は省ける。終わりは `<=` である。
- **初めて出たイベント種別:** 直前の同じ長さの期間に無かった種別を、最大スコアの降順 → 最初の時刻の昇順で返す（`pick_new_event_types`、760 行）。起点では切らず、期間の全体を使う。
- **移行:** alembic の最新は `a0b1c2d3e4f5`（`alembic/versions/a0b1c2d3e4f5_add_inventory.py`。単一の head。実装時に確かめ直す）。`log_records` に索引を足す移行は、起動時に終わるまで取り込みを止める（`docs/operations/backend-operations.md` の 5.4 節、619 行〜）。
- **CI:** PostgreSQL のジョブの `-k` は、その段に並べたファイルの中にしか効かない（`.github/workflows/ci.yml` の 214-225 行）。

## 2. 型の作り方

型は、ログの 1 行目から時刻・数値・ID などを伏せた文字列である。`services/log_patterns/masking.py`（新規）に、純粋関数として置く。取り込み・埋め戻し・シードは、すべてこの関数を使う。

### 手順

1. `message` の 1 行目だけを使う。複数行の記録の 2 行目以降は、スタックトレースなどで型を細かく割りすぎるためである。
2. 伏せる前に、1 行目を 2,000 文字で切る。巨大な 1 行で正規表現が遅くならないようにするためである。
3. 先頭の時刻（リモートログ収集の `STAMP` と同じ形）と、続く空白を取り除く。
4. 下の表の順に置き換える。**置き換えた部分（`<…>`）は、後の規則で触らない。**
5. 最後に数を伏せる（表の 12）。置き換えた部分と、残すと決めた 2 桁以下の `0x` の値は、数の規則でも触らない。
6. 連続する空白を 1 つにし、前後の空白を除く。500 文字を超えたら切る。
7. 関数は例外を出さない。途中で失敗したら、決めた型 `<UNPARSED>` を返す。

順が大事である。WWN・MAC・IP を時刻より先に当てないと、`HH:MM:SS` の規則が VMware の MAC（`00:50:56:…`）や FC の WWN（`20:00:…`）の先頭を時刻と見なして壊す。パスを時刻と UUID より先に当てないと、パスの中の日付や UUID でパスが割れる（`/var/log/2024-01-02.log` など）。

| 順 | 対象 | 置き換え |
|---|---|---|
| 1 | hostd・vpxa・vpxd の `[Originator@<数> …]` | `[sub=<値>]`（`sub=` だけを残す。`opID=`・`user=` などは消す。`sub=` の値の中のパスは 7 で伏せる） |
| 2 | 秘密の値。ラベルなしでは `Bearer` の直後の値だけを伏せる。直前が行頭か ASCII 英数字以外（`_` を含む）の `password`・`passwd`・`pwd`・`secret`・`token`・`apikey`・`api_key`・`session`・`cookie`・`authorization`（引用符で囲まれていてもよい）に `=` か `:` が続くときの値。引用符で囲まれた値はその内側を、引用符が無い値は空白・`]`・`,`・`;` までを対象とする。秘密の語に続く値が `Bearer`・`Basic`・`Digest`・`Negotiate`・`NTLM` とその認証情報なら、方式と認証情報を伏せる。大文字小文字は区別しない。 | `Bearer <SECRET>`・`<SECRET>`（ラベル付きで方式と認証情報が並ぶ場合は `<SECRET> <SECRET>`） |
| 3 | 1 の外の `opID=`・`user=` の値（`]` か空白まで） | `<ID>`・`<USER>` |
| 4 | URL（`スキーム://…`） | `<URL>` |
| 5 | WWN（16 進 2 桁を `:` で 8 つ）、MAC（16 進 2 桁を `:` か `-` で 6 つ） | `<WWN>`・`<MAC>` |
| 6 | IPv4（ポート付きを含む）。IPv6 は、8 組そろったものと、`::` の前後に 16 進の数字が少なくとも 1 つあるものだけ（単独の `::` は除く） | `<IP>` |
| 7 | パス: 行の先頭か、空白・`:`・`=`・`"`・`'`・`(`・`[` の直後の `/` から始まる語。`[データストア名] ` に続く語のうち、`.vmx`・`.vmdk`・`.vmsd`・`.nvram`・`.log`・`.vswp`・`.vmxf` で終わるもの（`[Originator`・`[sub=` は除く） | `<PATH>` |
| 8 | 本文中の時刻（ISO 8601 の日付と日時、`HH:MM:SS`） | `<TIME>` |
| 9 | UUID（`8-4-4-4-12` の 16 進）と、VMFS の UUID（`8-8-4-12`） | `<UUID>` |
| 10 | ストレージの装置の名前（`naa.`・`eui.`・`t10.`・`mpx.` で始まる語）と、HBA のパス（`vmhba<数>:C<数>:T<数>:L<数>`） | `<DEV>`・`<HBAPATH>` |
| 11 | `0x` に続く 3 桁以上の 16 進と、a-f を 1 文字以上含む 8 桁以上の 16 進の並び | `<HEX>` |
| 12 | 数（小数を含む）。語の中の数も伏せる（`cpu12` → `cpu<N>`、`esx-01` → `esx-<N>`）。単位は残す（`523ms` → `<N>ms`） | `<N>` |

- 2 桁以下の `0x` の値（SCSI の `H:0x0 D:0x2`、sense の `0x6 0x29 0x0`、コマンドの `0x2a`）は残す。調査で最も大事な違いがこの値にあるためである。
- 名前（VM 名、ホスト名、データストア名）は伏せない。名前を伏せる規則は誤りが多く、型の意味が読めなくなるためである。ただし、名前の中の数は 12 で伏せる。その結果、VM ごとに型が分かれることがある（8 章）。
- 8 桁未満で a-f を含む短い 16 進（`1a2b` など）は、数の規則で `<N>a<N>b` のように一部だけ伏せる。値ごとに型が割れることがある（8 章）。

### 確かめた例

scratchpad の試作（上の規則のとおりの正規表現）で、次の結果になることを確かめた。行は、公開されている形を元に作った架空の行である。PR B のテストに、この入力と出力をそのまま入れる。

| ログ | 入力（先頭の時刻は省略） | 型 |
|---|---|---|
| vmkernel | `cpu12:2097612)NMP: nmp_ThrottleLogForDevice:3893: Cmd 0x2a (0x45b8c1234567) to dev "naa.600508b1001c4d5e" on path "vmhba64:C0:T0:L1" Failed: H:0x0 D:0x2 P:0x0 Valid sense data: 0x6 0x29 0x0.` | `cpu<N>:<N>)NMP: nmp_ThrottleLogForDevice:<N>: Cmd 0x2a (<HEX>) to dev "<DEV>" on path "<HBAPATH>" Failed: H:0x0 D:0x2 P:0x0 Valid sense data: 0x6 0x29 0x0.` |
| hostd | `In(166) Hostd[2099123]: [Originator@6876 sub=Vimsvc.TaskManager opID=abc-12-ff user=vpxuser:<no user>] Task Created : haTask-ha-root-pool-vim.ResourcePool.updateConfig-123456` | `In(<N>) Hostd[<N>]: [sub=Vimsvc.TaskManager] Task Created : haTask-ha-root-pool-vim.ResourcePool.updateConfig-<N>` |
| hostd | `info hostd[2099123] [Originator@6876 sub=Vmsvc.vm:/vmfs/volumes/5f1a2b3c-1234abcd-ef01-0050568a1b2c/web01/web01.vmx opID=x user=root] State Transition (VM_STATE_ON -> VM_STATE_OFF)` | `info hostd[<N>] [sub=Vmsvc.vm:<PATH>] State Transition (VM_STATE_ON -> VM_STATE_OFF)` |
| vpxa | `verbose vpxa[2100001] [Originator@6876 sub=vpxLro opID=lro-1] [VpxLRO] -- BEGIN lro-12345 -- vpxa -- vpxapi.VpxaService.retrieveChanges -- 52a3c3e1-8f1b-4e7c-9d2a-1234567890ab` | `verbose vpxa[<N>] [sub=vpxLro] [VpxLRO] -- BEGIN lro-<N> -- vpxa -- vpxapi.VpxaService.retrieveChanges -- <UUID>` |
| vpxd | `error vpxd[00123] [Originator@6876 sub=vpxdVdb] [VdbStatement] SQL execution failed: password=hunter2 at 2024-01-02T10:20:30Z after 523ms on 10.0.0.12:5432 (esx-01.lab) [datastore1] web01/web01.vmdk` | `error vpxd[<N>] [sub=vpxdVdb] [VdbStatement] SQL execution failed: password=<SECRET> at <TIME> after <N>ms on <IP> (esx-<N>.lab) <PATH>` |
| vmkernel | `cpu3:2097152)WARNING: NFS: 1234: Lost connection to server 192.168.1.10 mount point /vmfs/volumes/abcd1234-5678efab dead:beef:0:1 fe80::1 00:50:56:8a:1b:2c 10:20:30 12345678 1234567 deadbeef12 https://vc.example/sdk?x=1` | `cpu<N>:<N>)WARNING: NFS: <N>: Lost connection to server <IP> mount point <PATH> dead:beef:<N>:<N> <IP> <MAC> <TIME> <N> <N> <HEX> <URL>` |
| vmkernel | `cpu0:2097150)ScsiPath: 1234: Path vmhba2:C0:T1:L5 WWN 20:00:00:25:b5:00:00:0f on 2001:db8::10:20:30 at 10:20:30 Foo :: bar` | `cpu<N>:<N>)ScsiPath: <N>: Path <HBAPATH> WWN <WWN> on <IP> at <TIME> Foo :: bar` |
| vpxd | `info vpxd[1] cookie=abc; Authorization: Bearer eyJhbGciOi.x.y "password":"p@ss" password: x [HostCtl] host/foo.bar https://10.0.0.1:443/sdk?id=1` | `info vpxd[<N>] cookie=<SECRET>; Authorization: <SECRET> <SECRET> "password":<SECRET> password: <SECRET> [HostCtl] host/foo.bar <URL>` |

`Authorization: Bearer …` は、2 の認証方式の規則と秘密の語の規則の両方が当たり、`<SECRET>` が 2 つ並ぶ。`Authorization: Basic …` なども同じである。`db_password` のように `_` が直前にある語でも値を伏せる。

試作の速さは、12,000 行で 1.2 秒（1 行あたり約 0.1 ミリ秒）だった。2,000 文字を超える 1 行も 3 ミリ秒で終わった。

### キーと版

- ログの種類は、前後の半角空白を除き、ASCII の大文字を小文字に揃える（`hostd` と `Hostd` を同じにする）。SQL では `lower(trim(log_kind))` を使い、PostgreSQL では `lower` の引数に `COLLATE "C"` を指定する。
- 型のキー（`pattern_key`）は、`sha256(f"{MASK_VERSION}\0{揃えたログの種類}\0{型}")` の 16 進の先頭 32 文字とする。
  - キーに vCenter は含めない。台帳とログの表は、どちらも `(vcenter_id, pattern_key)` の組で引く（3・4 章）。
  - 500 文字で切った後の型から作るので、先頭 500 文字が同じ長い行は同じ型になる。
- `MASK_VERSION`（整数）は、伏せ方の規則を変えるたびに上げる。版の扱いは 3 章に書く。

### 重大度の揃え方

取り込み・埋め戻し・API で、1 つの表を共有する（`services/log_patterns/severity.py`）。値はログの種類と同じく、前後の半角空白を除いて ASCII の大文字を小文字に揃えてから引く。タイムラインの `_LOG_LEVEL_BY_SEVERITY` と同じ語を含める。

| 順位 | 語 |
|---|---|
| 4 | `critical`・`crit`・`fatal`・`panic`・`alert`・`emerg` |
| 3 | `error`・`err` |
| 2 | `warning`・`warn` |
| 1 | `info`・`notice`、表に無い語、None |
| 0 | `debug`・`verbose`・`trivia` |

「warning 以上」は順位 2 以上とする。SQL で数えるときは、順位 2 以上の語の集合で `lower(trim(severity)) IN (...)` とする。PostgreSQL では `lower` の引数に `COLLATE "C"` を指定する。

## 3. 保存の形（PR B）

### ログの表に足す列

- `pattern_key`（`String(32)`、NULL 可）と `pattern_version`（`SmallInteger`、NULL 可）。
- 索引 `(vcenter_id, pattern_key, effective_at)` を足す。
- 取り込み（`_persist_batch`）とシードで、行を入れる前に型とキーを計算して入れる。プラグインの API は変えない（本体が計算する）。
- 取り込みで、`occurred_at`・`collected_at`・`effective_at` を UTC に揃えてから入れる。SQLite では時刻を文字列で比べるので、台帳とログの表で時刻の形が違うと、期間の条件が食い違うためである。

### 型の台帳（新しい表 `log_patterns`）

| 列 | 内容 |
|---|---|
| `id` | |
| `vcenter_id` | FK → `vcenters.id`、`ON DELETE CASCADE` |
| `log_kind` | 揃えたログの種類 |
| `pattern_key`・`pattern_version` | |
| `template` | 型の文字列（500 文字まで） |
| `first_seen_at`・`last_seen_at` | 初めて見た時刻と、最後に見た時刻（ログの `effective_at` を UTC に揃えたもの） |
| `total_count` | これまでに見た行数（`BigInteger`） |
| `max_severity_rank` | これまでに見た最も重い重大度の順位（整数） |
| `warning_first_seen_at` | warning 以上の行を初めて見た時刻（無ければ NULL） |
| `warning_first_source_id` | その行の `source_id` |

- 一意制約は `(vcenter_id, pattern_key)`。索引は `(vcenter_id, first_seen_at)` と `(vcenter_id, warning_first_seen_at)`。
- 台帳には、生のログ（`message`）を入れない。型だけを入れる。

### 台帳の開始の表（新しい表 `log_pattern_baselines`）

慣らしの期間（後述）を決めるため、台帳をいつ作り始めたかを、ログの出どころごとに残す。

| 列 | 内容 |
|---|---|
| `vcenter_id` | FK、`ON DELETE CASCADE` |
| `source_id`・`log_kind` | ログの出どころ（ホストとログの種類）。`log_kind` は揃えた値 |
| `pattern_version` | |
| `started_at` | この出どころの台帳を作り始めた実時刻（ログの時刻ではない） |

- 主キーは `(vcenter_id, source_id, log_kind, pattern_version)`。一度入れた `started_at` は動かさない。
- `collector_id` は主キーに含めない。別のプラグインが同じ `source_id` を使っても、同じ出どころとして開始を共有する。開始は慣らしの期間にしか使わないので、共有しても判定は変わらない。
- 取り込みで、今の版の行が無い出どころのログが来たら、`started_at` を今の時刻にして入れる（`ON CONFLICT DO NOTHING`）。
- 移行のときにある出どころ（ログの表にある `(vcenter_id, source_id, 揃えた log_kind)`）は、移行の時刻を `started_at` にして入れる。`vcenters` に対応する行が無い孤児ログは残し、開始の行と台帳の行は作らない。

### 埋め戻しの状態の表（新しい表 `log_pattern_backfill_state`）

| 列 | 内容 |
|---|---|
| `pattern_version` | 主キー |
| `upper_id` | 埋め戻しの終わりの id。移行では NULL で入れ、最初に記録した `pending_upper_id` が確定できる実行でその値を入れる |
| `last_id` | 埋め戻しが進んだ id |
| `completed_at` | 埋め戻しが済んだ実時刻 |
| `pending_upper_id` | 以前の実行の始まりに記録した `log_records.id` の最大（行が無ければ 0） |
| `pending_recorded_at` | `pending_upper_id` を観測した実時刻。観測から 270 秒以上たつと確定に使える |

`upper_id` を移行ではなくジョブで決めるのは、移行のあとも古いコードがしばらく動くことがあるためである（`docs/operations/backend-operations.md` の 5.4 節は、先に 1 つのプロセスで移行を済ませる手順を案内している）。

**確定の規則:** 実行の始まりに記録した `max(id)`（`pending_upper_id`）は、`pending_recorded_at` から 270 秒以上たった実行でだけ `upper_id` や `last_id` の確定に使う。早い実行では、記録済みの値と時刻を残す。ジョブの間隔は 5 分である。観測からの待ち時間を 30 秒短くして、実行開始時刻のずれで確定が次の回に延びるのを避ける。

PostgreSQL では、id は挿入時に決まり、コミットはその後になる。例えば、古いコードが id 100 をコミットする前に別の取り込みが id 101 をコミットすることがある。境界を観測してから待つことで、後からコミットされた小さい id の行も読み取れる。

### 台帳の更新

- ログの挿入を、イベントと同じく `RETURNING` で入った行（id・型のキー・時刻・重大度・出どころ）を返す形に変える。`RETURNING` を付けると、SQLite では `rowcount` が常に `-1` になるので、ログの件数も返った行で数える（[イベントの対象の保存](2026-11-23-event-entities.md)の計画書で確かめた事実）。
- バッチの終わりに、返った行（`ON CONFLICT DO NOTHING` で入った行だけ）を型ごとにまとめる。時刻は UTC に揃えてから、最初と最後の時刻、行数、最も重い順位、warning 以上の最初の時刻とその出どころを求める。
- 台帳へは `INSERT ... ON CONFLICT (vcenter_id, pattern_key) DO UPDATE` で入れる。
  - SQLite には `LEAST`・`GREATEST` が無く、2 引数の `min`・`max` は NULL を返す。そのため、比べる式は両方の DB で `CASE WHEN` と `COALESCE` で書く（例: `warning_first_seen_at = CASE WHEN excluded.warning_first_seen_at IS NULL THEN log_patterns.warning_first_seen_at WHEN log_patterns.warning_first_seen_at IS NULL OR excluded.warning_first_seen_at < log_patterns.warning_first_seen_at THEN excluded.warning_first_seen_at ELSE log_patterns.warning_first_seen_at END`）。
  - 行数は足し、順位は大きいほうを取る。`warning_first_source_id` は、`warning_first_seen_at` を変えたときだけ変える。
  - 入れる順は、キーの順に並べる（PostgreSQL で、並行するバッチがデッドロックしないように）。
- 同じ vCenter のログを、別のプラグインのバッチや埋め戻しのジョブが同時に更新することがある。台帳の更新は、ログの挿入と同じトランザクションの最後に置き、トランザクションを長くしない。PostgreSQL で並行のテストを足す。

### 埋め戻し（新しいジョブ `log_pattern_backfill`）

導入の時点で、ログの表には最大 7 日分の行がキーを持たずに残っている。また、伏せ方の版を上げると、古い版のキーが残る。これらを埋めるジョブを足す。

ジョブは、埋め戻しと追いつきの 2 段で動く。どちらの段でも、実行の始まりに、確定の規則に従って次を行う。

- `pending_upper_id` が NULL なら（最初の実行）、`max(id)` とその観測時刻を記録するだけで終わる。`upper_id` が NULL の間は、確定できる実行で `upper_id` に `pending_upper_id` を入れて埋め戻しを始める。
- 記録済みの境界を確定に使えるとき、今の `max(id)` とその観測時刻を、この実行の終わりに記録する（追いつきで使う）。

**埋め戻し**（`completed_at` が入るまで）:

- 対象は、`id > last_id AND id <= upper_id` の行。主キーの順に `LIMIT 5000` で読む。読んだ行のうち、`pattern_key IS NULL OR pattern_version != :版` のものだけを処理する（`!=` にするのは、コードを前の版に戻したときに、新しい版の行も直すため）。
- 5,000 行ごとに 1 トランザクションにし、行の更新・台帳の更新・`last_id` の更新を同じトランザクションで行う。
  - 行の更新には `AND (pattern_key IS NULL OR pattern_version != :版)` を付け、`RETURNING` で実際に更新した行だけを台帳に足す（取り込みやほかの実行と二重に数えないため）。
  - 行ごとにキーが違うので、`UPDATE ... FROM (VALUES ...)` の 1 文にするか、1 行ずつの `UPDATE ... RETURNING` にする。SQLAlchemy の両方の方言で動くほうを、PR B で確かめて決める。
- 1 回の実行で最大 50,000 行までとし、残りは次の実行に回す。ジョブの間隔は 5 分にする。ログが 605 万行（`docs/operations/backend-operations.md` の 5.4 節で、移行の計測に使った行数）なら、埋め終わるまで 10 時間ほどかかる。PR B で計測し、文書に書く。
- 終わりの判定: 読んだ行が `LIMIT` より少なければ、`last_id` を `upper_id` にする。`upper_id` の行が保持の削除や vCenter の削除で先に消えていても、埋め戻しが終わるようにするためである。
- `last_id` が `upper_id` に達したら、`completed_at` を入れ、`pattern_version != 版` の台帳の行を消す。`upper_id` は 270 秒以上前に観測した値なので、`upper_id` 以下の行は、その間に遅れてコミットされたものも含めて読んでいる。

**追いつき**（`completed_at` が入ったあと、毎回の実行）:

古いコードと新しいコードが同時に動く間（先に 1 つのプロセスで移行を済ませる手順のとき）や、PR B より前のコードに一時的に戻した間は、キーの無い行が `upper_id` より後にも入る。完了は、古いコードが止まったことを保証しない。そこで、完了したあとも、ジョブは毎回次を行う。

- `id > last_id` の行を、埋め戻しと同じ方法（主キーの順に 5,000 行ずつ、1 回で最大 50,000 行）で読み、キーが無いか今の版でない行を直して台帳に足す。
- `id > last_id` の行は、今の `max(id)` まで読む。ただし、実行の終わりに `last_id` に入れるのは、記録済みの `pending_upper_id` と、読み終えた最後の id のうち小さいほうである（確定の規則。1 回で最大 50,000 行のため、読み終えていないこともある）。記録から 270 秒未満の場合も行は読むが、`last_id` は更新しない。確定に使えたときは、そのあとに `pending_upper_id` と `pending_recorded_at` を更新する。`pending_upper_id` より後の行は、次の実行でもう一度読むので、そのあいだに遅れてコミットされた行も読める。
- `pattern_version != 版` の台帳の行を消す（古いコードが作り直した行を消すため）。
- ふだんは、読む行のすべてに新しいコードがキーを付けているので、前回の実行から 5 分のあいだに入った行を主キーの範囲で読むだけで終わる。PR B で、この読み取りの時間も計測する。
- 古いコードが入れた行は、次の実行（最大 5 分後）で型が付く。それまでのあいだ、その行は「型の計算待ち」になり、台帳にも入らない。

伏せ方の関数は例外を出さない（2 章）ので、1 行の失敗で埋め戻しや追いつきが止まることはない。

### 版を上げる手順

`MASK_VERSION` を上げるときは、必ず移行を 1 本足す。版を上げる処理は移行だけで行い、ジョブでは行わない。新しいコードの取り込みが、ジョブより先に新しい版の開始の行を作ってしまうのを防ぐためである。

1. 移行の中に、古い版と新しい版の番号を定数で書く（`MASK_VERSION` を import しない。新しく導入する環境で古い移行を流し直したとき、後の版の値が入らないようにする）。
2. 古い版の台帳の行、開始の行、状態の行を消す。
3. 新しい版の開始の行を、移行の時刻で入れる。出どころは、古い版の開始の表と、ログの表の `DISTINCT (vcenter_id, source_id, 揃えた log_kind)` の両方から集める（最初の移行では、ログの表だけから集める）。
4. 新しい版の状態の行を、`upper_id` を NULL、`last_id` を 0 にして入れる。
5. ログの表の行は、埋め戻しのジョブが新しい版のキーにする。

PR B の最初の移行も、版 1 について同じ 3・4 を行う。PR B より前のコードに戻した場合は、戻した間のログに型が付かず、「型の計算待ち」になる。新しいコードに戻せば、追いつきで型が付く。これを `backend-operations.md` の 5.5 節（ロールバックの手順）に書く。テストで、最新の移行を当てたあとの状態の表の版が `MASK_VERSION` と一致することを確かめる。

古い版の台帳を消すので、版を上げると、ログの保持期間（7 日）より前の記憶は失われる（8 章）。

### 慣らしの期間

台帳を作り始めた直後は、どの型も「初めて」になる。そこで、ある型を「初めて出た型」とするのは、次の 3 つを満たすときだけにする。

- 今の版の状態の行の `completed_at` が入っている（埋め戻しが済んでいる）。埋め戻しが済むまでは、ほかの出どころの古い行で `warning_first_seen_at` が前に動くことがあるためである。
- その型の `warning_first_source_id` の出どころの開始の行がある。無ければ、慣らしの期間として扱う。
- `warning_first_seen_at >= started_at + LOG_PATTERN_WARMUP_DAYS`（既定 3 日）。

`started_at` は実時刻なので、初回の収集でローテート済みの古いファイルを読んでも、慣らしの期間はすぐには終わらない。ESXi を 1 台足したときも、そのホストの型は 3 日のあいだ「初めて」にならない。導入の直後と版を上げた直後は、埋め戻しが済み、かつ 3 日が過ぎるまで「初めて出た型」を判定しない。

### 削除

- 台帳の行は、`last_seen_at` が `LOG_PATTERN_RETENTION_DAYS`（既定 90 日）より古くなったら消す。`purge_old_logs` と同じジョブから呼ぶ。
  - 設定の検証で、この値は `0` か、`LOG_RETENTION_DAYS` 以上に限る。
  - `0` は、ほかの保持の設定と同じく、期間による削除をしない（上限による削除は行う）。
- 1 つの vCenter の台帳が `LOG_PATTERN_MAX_PER_VCENTER`（既定 20,000）行を超えたら、`last_seen_at` の古い順に消す。ただし、消すのは `last_seen_at` がログの保持期間より古い行だけにする。ログの表にキーが残っている型の台帳の行は消さない。
- これにより、今の版のキーを持つログの行には、必ず台帳の行がある。
- vCenter を消すと、台帳と開始の表も CASCADE で消える。状態の表は版ごとなので、vCenter とは関係しない。

## 4. API（PR C）

### ログの型ごとの集計

- `GET /api/logs/patterns`（viewer 以上）を足す。絞り込みは `GET /api/logs` と同じ条件（`log_conditions`）を使う。ただし、`from` と `to` は必須にする。
- `(vcenter_id, pattern_key)` で GROUP BY し、台帳と突き合わせる。返すもの:
  - 型ごとに、`vcenter_id`・`vcenter_name`・`pattern_key`・`log_kind`・`template`・期間内の行数・期間内の最初と最後の時刻・期間内の最も重い重大度・台帳の `first_seen_at`。
  - 行数の降順に最大 200 件、型の総数、打ち切ったか。
- キーが NULL の行、今の版でないキーの行（埋め戻しの前）、台帳に行の無いキーの行は、「型の計算待ち」として 1 行にまとめ、件数だけを返す。
- 読む行数の上限を設ける。`LIMIT 上限 + 1` の副問い合わせで、条件に合う行が `LOG_PATTERN_SCAN_MAX_ROWS`（既定 500,000）を超えるかを確かめ、超えたら 422 にし、期間か条件を絞るよう返す。数えるのは、タイムラインと同じ集計の枠（`aggregation_slot`）の中で行う。本文の部分一致は `message` を読むので重い。PR C で、行数と秒数を計測する。
- `GET /api/logs` に `pattern_key` の絞り込みを足す（型から一覧に移るため）。CSV の出力にも同じ条件を通す。

### タイムラインの「初めて警告以上で出たログの型」

- 意味は「この環境で、初めて warning 以上の重大度で出た型」である。info で前から出ていた型が、初めて warning 以上で出た場合も含む。画面とユーザーガイドの見出しも、これに合わせる。
- `IncidentTimelineHighlights` に、次の項目を足す。すべて既定値を持たせ、足す前に保存した結果が読めるようにする。
  - `new_log_patterns: list[IncidentTimelineNewLogPattern] | None = None`。None は「判定していない」（足す前に保存した結果、または `sources` に `log` が無い）。
  - `new_log_patterns_total: int = 0`
  - `log_patterns_backfill_pending: bool = False`（埋め戻しが済んでおらず、判定していない）
  - `log_patterns_warming_up: list[IncidentTimelineLogPatternWarmup] = []`（慣らしの期間で判定していない出どころ。`vcenter_id`・`vcenter_name`・`source_id`・`host`・`log_kind`・慣らしが終わる時刻を持つ。最大 20 件）
  - `new_log_patterns_out_of_retention: bool = False`（期間の始まりがログの保持期間より前で、行を数えられないことがある）
- 選び方:
  0. 埋め戻しが済んでいなければ、`new_log_patterns` を `[]`、`log_patterns_backfill_pending` を true にして返す。画面と報告書は、`log_patterns_backfill_pending` を先に見て「判定していない」と出す。
  1. 台帳から、`warning_first_seen_at` が期間 `[from, to)` にあり、慣らしの期間を過ぎた型を選ぶ。型が `<UNPARSED>` のものは除く。vCenter の絞り込みは台帳の `vcenter_id` に当てる。起点では切らない（初めて出たイベント種別と揃える）。
  2. 選んだ型について、期間内の warning 以上の行を、ログの表から `(vcenter_id, pattern_key)` の組で数える（500 件ずつ）。対象の絞り込みは `_log_filters` と同じ扱いにする（`host` に当て、moid を指定したら完全一致、moid だけの指定なら空）。行が 0 件の型は除く。
  3. 最も重い重大度の降順 → 最初の時刻の昇順 → キーの順で、最大 10 件を返す。
- `IncidentTimelineNewLogPattern` は、`vcenter_id`・`vcenter_name`・`pattern_key`・`log_kind`・`template`・期間内の行数・最初の時刻・最も重い重大度・ホストの名前（最大 3 つ）・台帳の `first_seen_at` と `warning_first_seen_at` を持つ。

### 出力（案 10）

- 報告書のハイライトに「### 初めて警告以上で出たログの型」の節を足す。型は外から来た文字列なので、既存の無害化（コードスパン）を通す。None なら「判定していません」と書く。慣らしの期間と保持期間の注記も書く。
- `result.json` は、足した項目がそのまま入る。

## 5. 画面と文書（PR D）

- **ログタブ:** 「一覧」と「型ごと」を切り替える。
  - 型ごとの表は、型・ログの種類・vCenter・行数・最初と最後の時刻・最も重い重大度・「初めて見た時刻」の列を持つ。
  - 行を押すと、その型（`pattern_key` と vCenter）で絞った一覧に移る。
  - 上限で打ち切ったとき、「型の計算待ち」の行があるとき、422 のとき（期間を絞るよう案内）に、注記を出す。期間を指定していなければ、型ごとの表は期間の指定を求める。
- **タイムライン:** ハイライトに「初めて警告以上で出たログの型」のカードを足す。
  - 1 件ごとに、型、ログの種類、ホスト、vCenter、行数、最初の時刻、重大度を出す。
  - 操作は「ここを起点にする」（最初の時刻）と「ログで開く」（その型と期間で絞ったログタブ）。
  - 空・None・慣らしの期間・保持期間の注記を出し分ける。
- **文書:**
  - `docs/userguide/remote-log-collector.md` の「収集と検索の既定値」（116 行）に、型の説明を足す。伏せる規則、名前は伏せないこと、台帳の保持期間、慣らしの期間を書く。
  - `docs/userguide/timeline.md` の「ハイライト」（93 行〜）に、カードの説明を足す。
  - アプリ内ヘルプ（`frontend/src/help/tabHelpContent.ts` の 28 行のログ、57 行のタイムラインのハイライト）。
  - 仕組みの説明を `docs/features/log-pattern-detection.md` に書く（[構成変更の検出の仕組み](../features/config-change-detection.md)と同じく、です・ます体のフォーマルな文体にする）。
  - CHANGELOG を更新する。

設定と運用の文書（`docs/operations/backend-operations.md` の定期ジョブ（2.3 節）・保持の設定・移行の所要時間の表（5.4 節）、`.env.example` の保持の並び（104-111 行））は、設定とジョブを足す PR B と PR C で直す。

## 6. PR の分け方

### PR A: 本書

本書だけ。

### PR B: 型の付与と台帳

- `services/log_patterns/masking.py`・`severity.py` とテスト。
  - 2 章の例の入力と出力。
  - 版やログの種類の違いでキーが変わること。大文字小文字の違うログの種類が同じキーになること。
  - 2,000 文字で切ってから伏せ、500 文字で切ること。
  - 1 万行の伏せ方の時間（目安として記録する。テストの合否には使わない）。
- 移行: `log_records` に 2 列と索引を足し、`log_patterns`・`log_pattern_baselines`・`log_pattern_backfill_state` を作る。版 1 の開始の行と状態の行も入れる（3 章の「版を上げる手順」の 3・4）。
  - 移行のテストを、既存の手本に倣って足す。
  - 索引を足す時間と、今ある出どころを集める時間（ログの表を全部読む）を計測し、`backend-operations.md` の 5.4 節の表に足す。
- 取り込み: 時刻を UTC に揃え、ログの挿入を `RETURNING` に変え、キーを入れ、台帳と開始の表を更新する。件数は返った行で数える。
- 埋め戻しのジョブ、台帳の削除、設定と検証（`LOG_PATTERN_RETENTION_DAYS`・`LOG_PATTERN_MAX_PER_VCENTER`・`LOG_PATTERN_WARMUP_DAYS`）。`backend-operations.md` と `.env.example` を直す。
- シード: 同じ関数でキーを付け、台帳と開始の表も入れる。
  - 同じ型の行が数値違いで並ぶログと、障害の前に初めて warning 以上で出る型を入れる。
  - 慣らしの期間を過ぎ、埋め戻しが済んだ状態にする。
  - モックの収集はログを出さないので、モックには足さない。
- テスト:
  - 台帳の更新（時刻の最小・最大、行数、順位、warning の最初の時刻と出どころ）。
  - 「NULL の後に warning が来る」を SQLite と PostgreSQL の両方で確かめる。
  - 同じバッチの重複。`ON CONFLICT` で入らなかった行を数えないこと。
  - 埋め戻し（NULL と今の版でない行、`upper_id` が記録から 270 秒以上たった実行で決まること、`upper_id` までで止まること、取り込みとの二重の数えの防止、`completed_at` を入れたあとは追いつきだけをすること）。
  - 版を上げたときの手順（移行のあとの台帳・開始・状態の表）と、状態の表の版が `MASK_VERSION` と一致すること。
  - 伏せ方の関数が失敗したとき `<UNPARSED>` になること。
  - `upper_id` の行と途中の行を消してから埋め戻しても、完了すること。
  - 確定の規則: 最初の実行は `pending_upper_id` を記録するだけで終わること。`upper_id` より小さい id の行が、`upper_id` を記録したあとに入っても（遅れてコミットされた行を、id を指定した挿入で再現する）、埋め戻しで直ること。完了の直後と追いつきでも同じであること。
  - 完了したあとにキーの無い行（古いコードの行）が入っても、次の実行の追いつきで型が付き、台帳に入ること。今の版でない台帳の行が消えること。
  - 削除（期間、上限、ログの保持期間の中の型を消さないこと）。
  - 慣らしの期間（埋め戻しが済む前、開始の行が無い出どころ、新しい出どころ、ローテート済みの古いファイル）。
  - UTC 以外の時刻で入ったログの時刻が UTC に揃うこと。
  - PostgreSQL の並行の更新。
- CI: 新しいテストのファイルを PostgreSQL の段の一覧に足し、`-k` に `log_pattern` を足す。移行のテストは、移行の段（217 行）の `-k` に足す。
- CHANGELOG。

### PR C: API

4 章のとおり。`LOG_PATTERN_SCAN_MAX_ROWS` の設定と文書も足す。テストは次のとおり。
- 集計の結果（vCenter ごとの組、計算待ち）
- 上限での 422、`from`・`to` が無いときの 422
- `pattern_key` の絞り込み
- 初めて出た型の選び方（慣らし、warning 以上、vCenter の組、対象の絞り込み、moid だけの指定、並び、上限、保持期間の注記）
- 足す前の保存結果が読めること
- 報告書の節
- 計測（行数と秒数）

### PR D: 画面と文書

5 章のとおり。スクリーンショットを PR に添える。

各 PR は origin/main から作ったブランチで進める。実装は Codex（gpt-6.2-sol）に任せ、critic がレビューする。Codex には、ブラウザを起動しないよう依頼文に書く。全体のテストと、画面の確認・スクリーンショットは Claude 側で行う。

## 7. 範囲外（後続）

- 型を使った障害パターン（案 5）の判定。
- 型ごとの件数の急増の検知（いつもより多い型）。
- 伏せ方の規則を、設定の画面で足し引きすること。
- 自動のクラスタリング（Drain など）。
- チャット（LLM）に型を渡すこと。
- パーサが `In(166)`・`Wa(164)` の形の重大度を読めるようにすること（リモートログ収集の変更）。
- 版を上げるときに、古い版の台帳の型の文字列に新しい規則を当てて、記憶を引き継ぐこと。

## 8. リスク

- **伏せ方が合わない:** 実機のログで、伏せ方が足りずに型が増えすぎること、伏せすぎて違う内容がまとまることがある。
  - 本書の例は、公開されている形を元にした架空の行である。PR B のマージの前に、利用者の許可を得て、開発環境の DB のログに伏せ方を当てる。確かめるのは、ログの種類ごとの行数・型の数と、重大度ごとの行数（None を含む）だけである。型の中身を読むかどうかは、そのときに利用者に聞く。
  - **確認の結果（2026-11-25）:** 利用者の許可を得て、開発環境の DB（SQLite）を読み取り専用で開き、PR B の伏せ方を当てた。利用者の判断で、型の中身は読んでいない。
    - ログは 112 万行（2026-11-17〜11-24、vCenter 1 台、出どころ 1 つ）で、すべて vpxd だった。ESXi のログ（vmkernel・hostd・vpxa）は無く、確かめていない。
    - 型は 228 個だった。行が 1 つだけの型は 31 個で、行数の多い 20 個の型で全体の 84% を占める。`<UNPARSED>` は 0 行だった。
    - 重大度は、info が 105.97 万行、warning が 3.92 万行、error が 2.19 万行、None が 12 行だった。
    - 日ごとの、新しく出た型の数（そのうち初めて warning 以上で出た型の数）は、次のとおりだった。11-17 が 141（19）、11-18 が 10（3）、11-19 が 71（24）、11-20 が 2（0）、11-23 が 4（1）。最初の 3 日を慣らしの期間とすると、そのあとに「初めて警告以上で出た型」になるのは 1 日に 0〜1 個である。11-19 の増え方の理由は、型の中身を読んでいないので分からない。
    - 伏せ方の時間は、112 万行で 104.5 秒（1 行あたり約 0.09 ミリ秒）だった。
  - 2 桁以下の `0x` を残すので、SCSI の状態の違いは別の型になる。逆に、3 桁以上の `0x` の値の違いは 1 つの型にまとまる。
- **重大度の読み取り:** パーサは語の `info`・`warning`・`error` などしか読まない。ESXi 7 以降の `In(166)`・`Wa(164)` の形では、本文に `error` などの語が無いと重大度が None になる。warning 以上の型を取りこぼすことがある。逆に、本文の `0 errors` のような語でも error になる。
- **名前で型が分かれる:** VM 名やデータストア名は伏せないので、VM ごとに型が分かれる。台帳の上限（20,000 行）で抑えるが、上限で消した型が再び出ると、「初めて出た型」に見える（ログの保持期間を過ぎた型だけを消すので、7 日以内には起きない）。
- **版を上げると記憶が失われる:** 伏せ方の版を上げると、古い版の台帳を消すので、型の記憶はログの保持期間（7 日）まで戻る。埋め戻しと慣らしの期間もやり直しになる。規則を足すだけの変更でも同じである。古い型の文字列に新しい規則を当てて台帳を移す方法は、範囲外とする（7 章）。
- **秘密の規則が普通の語も伏せる:** `:` の後の値も伏せるので、`Session: started for user root` は `Session: <SECRET> for user root` に、`Failed to read password: file not found` は `password: <SECRET> not found` になる。型が少しまとまるだけで、秘密を残す向きには誤らない。ラベルが無い `auto-negotiate enabled`・`Using basic mode for disk`・`content digest mismatch on file`・`Negotiate failed with peer` は伏せない。
- **空白を含む名前のパスは伏せない:** `[datastore1] My VM/My VM.vmx` のように空白を含むデータストアのパスは、パスとして伏せられず、VM ごとに型が分かれる。
- **伏せ方に失敗した行:** 失敗した行は、ログの種類ごとに `<UNPARSED>` の 1 つの型にまとまる。初めて出た型のカードからは除く。取り込みでは、失敗した件数を警告のログに出す。
- **追いつきで漏れる行:** 古いコードの取り込みが境界の確定後にコミットされると、確定した境界以下の id の行は、保持期間が過ぎるまで「型の計算待ち」になることがある。新しいコードの行には取り込みでキーが付くので、起きるのは古いコードと同時に動く間だけである。
- **SQLite の id の再利用:** SQLite のログの表は AUTOINCREMENT ではないので、最大の id の行が消えると、同じ id が再び使われる。古いコードと新しいコードが同時に動く間にこれが起きると、古いコードが入れた行の id が `last_id` 以下になり、追いつきで読まれない。その行は保持期間が過ぎるまで「型の計算待ち」になる。表を作り直して AUTOINCREMENT にする方法は、孤児の行で移行が失敗する危険と、移行の時間・ディスクに見合わないので採らない。
- **短い 16 進で型が割れる:** 8 桁未満で a-f を含む 16 進（スレッド ID など）は、一部だけが伏せられ、値ごとに型が分かれる。実機の確認で多ければ、規則を足して版を上げる。
- **台帳と保存した結果にログの語が残る:** 型には、ログの語（名前を含む）が残る。台帳は既定で 90 日残るので、ログの保持期間を過ぎても型は残る。タイムラインの結果に入った型は、スナップショットの保持期間のあいだ残り、出力した資料にも入る。ユーザーガイドと `backend-operations.md` に書く。台帳の保持期間は設定で短くできる。
- **取り込みの負荷:** 1 行ごとに正規表現をかける。試作では 1 行あたり約 0.1 ミリ秒だった。1 バッチ 1 万行なら 1 秒ほど延びる。
- **集計の負荷:** ログタブの型ごとの集計は、期間内の行をすべて読む。期間を必須にし、上限（500,000 行）を超えたら 422 にする。
- **埋め戻しの負荷:** 導入の直後は、最大 7 日分の行を埋め戻す。1 回 50,000 行に抑えるので、605 万行なら終わるまで 10 時間ほどかかる（実測は運用ガイドの 5.4 節）。その間は「型の計算待ち」の行が残り、慣らしの期間も終わらない。
- **移行の時間:** `log_records` に索引を足す移行は、起動時に終わるまで取り込みを止める。PR B で計測し、文書の表に足す。
