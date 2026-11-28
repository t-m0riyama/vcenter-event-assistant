# PDL（Permanent Device Loss）の障害パターンを足す

最終更新: 2026-11-28（PR B のレビューと進捗を反映）

Issue #398 の計画書である。[既知の障害パターンの計画書](2026-11-23-event-patterns.md)（以下「パターンの計画書」）の 10 章で後続に回した「PDL など、種別の名前を確かめられなかったパターン」のうち、PDL を足す。用語（moid・対象・役割）はパターンの計画書に合わせる。コードの場所は、バックエンドを `src/vcenter_event_assistant/` から、画面を `frontend/src/` から書く。行番号は、本書を書いた時点の main のものである。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| — | 実機で確かめる道具（`scripts/probe_event_types.py`） | マージ済み [PR #405](https://github.com/t-m0riyama/vcenter-event-assistant/pull/405) |
| A | 本書 | マージ済み [PR #406](https://github.com/t-m0riyama/vcenter-event-assistant/pull/406) |
| B | 種類 `occurrence`、デバイスの取り出し、パターン `pdl`、API・通知・調査資料・対応手順、画面のスキーマ、利用者ガイド | PR 作成済み [PR #407](https://github.com/t-m0riyama/vcenter-event-assistant/pull/407) |
| C | タイムラインの画面（デバイスの表示） | 未着手 |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

PDL は、ホストからストレージデバイス（LUN）が恒久的に失われた状態である。APD（All Paths Down）と違い、パスが戻るのを待っても回復しない。Broadcom KB 391710 の vSAN 8.x の事例では、同じディスクについて、ESXi の `vobd.log` に次の 2 つの種別が同時に記録されている。

- `esx.problem.scsi.device.state.permanentloss`
- `esx.problem.psastor.device.state.permanentloss`

2 つの種別を別々に数えると、1 回の障害が 2 件の検知になる。一方で、同じホストで同時に別のデバイスが失われたときは、別の障害として見せたい。そのため、ホストだけでなく、デバイスごとにまとめる必要がある。今の障害パターンは、ホストなどの moid ごとにしかまとめられない。

決めたこと（利用者の決定）:
- 先に読み取り専用の道具で実機を確かめ、その結果で本書を書く（PR #405）。
- 実機では実際のイベントが 0 件だったが、カタログの書式を根拠に本書を書く（2026-11-27）。
- 初版の 7 パターンは変えない。

## 1. 前提（調べて分かったこと）

### 実機の結果（vCenter 8、PR #405 の道具、直近 30 日）

- **カタログ:** 2 つの種別は、どちらも `EventEx`、分類は `error` で、本文の書式は同じだった。
  ```
  Device {1} has been removed or is permanently inaccessible. Affected datastores (if any): {2}.
  ```
  - デバイスの ID は引数 `{1}` で、本文の「Device」の直後に入る。データストアは引数 `{2}` に、名前の並びとして入る。
- **兄弟の種別:** どちらの種別にも、`.noopens`・`.pluggedback`・`.withreservationheld` が付いた種別がある。書式は確かめていない（道具は ID だけを出す）。`.pluggedback` は、名前から回復を表すとみられる。
- **APD:** 3 つの種別（`apd.start`・`apd.timeout`・`esx.clear.storage.apd.exit`）もカタログにあり、書式はパターンの計画書で公開情報から確かめたものと合っていた。
- **イベント:** vCenter に残るイベントにも、アプリの DB にも、対象の種別は 0 件だった。そのため、次は確かめられていない。
  - 2 つの種別が vCenter に同時に届くか、何秒の差で届くか
  - 2 つの種別が、同じデバイスを同じ表記で書くか（KB の `vobd.log` では同じだった）
  - 実際のイベントに `objectId`（ホスト）や基底の `host` が入るか

結果は Issue #398 と PR #405 のコメントに残した。

### 今の仕組み

- **保存するもの:** アプリはイベントの本文（`fullFormattedMessage`）を `events.message` に保存する（`collectors/events.py` の `normalize_event`）。本文が空なら `str(e)` を保存する（`collectors/events.py:124`）。EventEx の `arguments` は保存しない。そのため、デバイスの ID は本文から取り出す。
- **言語:** 本文は vCenter のセッションの言語で組み立てられる。道具（PR #405）は収集と同じ `collectors/connection.py` の `connect_vcenter` で接続し、英語の本文を得た。収集の本文も英語になる見込みである。
- **障害パターン:** `services/event_patterns/` にある。
  - 定義（`definitions.py`）の種類は `repeat` と `sequence` だけで、`repeat` の `min_count` は 2 以上である（`tests/services/test_event_patterns.py:36` が確かめる）。
  - 判定（`detection.py` の `detect_pattern`）は、`(vcenter_id, entity_moid)` ごとにイベントを分け、`sorted(grouped)` の順に判定する（44 行）。`repeat` 以外はすべて `_sequence` に送る（46 行）。
  - 問い合わせ（`query.py` の `_pattern_rows_statement`）は、子表 `event_entities` の対象の行を読む。本文は読まない。
- **検知を使う場所:**
  - タイムラインのハイライト（`services/incident_timeline_view.py:1169`、応答は `api/schemas/incident_timeline_view.py:212` の `IncidentTimelineDetectedPattern`）
  - 通知（`services/alerting/alert_eval_event_pattern.py`。`context_key` は `{vcenter_id}:{entity_moid}:{pattern_id}`。key ごとに最新の検知を 1 件だけ持つ（82-86 行））
  - 調査資料の出力（`services/incident_timeline_export.py:296-301`）
  - 対応手順（`services/diagnostics/procedures.py` の `BUILTIN_PROCEDURES`。すべてのパターンに手順があることを `tests/test_diagnostics_procedures.py:29` が確かめる）
  - パターンの一覧の API（`GET /api/event-patterns`）
- **画面のスキーマ:** パターンの一覧の zod（`api/schemas/eventPatterns.ts:10-13`）は、`kind` を `['repeat', 'sequence']` に、`min_count` を 2 以上か null に限る。一覧はアラートルールの画面（`panels/settings/AlertRulesPanel.tsx`）と、タイムライン（`panels/timeline/TimelinePanel.tsx:107`、判定を省いたパターンの名前）が読む。新しい種類を足すと、この 2 つで一覧が読めなくなるので、スキーマは種類を足す PR で一緒に直す。
- **診断コマンドの引数:** `esxi.device` の引数 `device` は、`[A-Za-z0-9][A-Za-z0-9._:-]{0,127}` に限られる（`services/diagnostics/catalog.py:15`）。下線は許すので、`t10.ATA_____…` のような ID も渡せる。空白は拒む。値はコマンドに入れる前に `shlex.quote` される（`catalog.py:92`）。

## 2. 設計

### 種類 `occurrence`（発生）

PDL は 1 件で障害を表すので、回数や並びで判定する今の種類に当てはまらない。種類 `occurrence` を足す。

- **定義:** `steps` は 1 つ、`min_count` は None、`collapse_seconds` は 1 以上。`within_minutes` は `ceil(collapse_seconds / 60)` と等しくする（定義の検査で確かめる）。窓は使わない。
- **判定:** 窓を使わない専用の処理（`_occurrence`）にする。`detect_pattern` に分岐を足す。
  - まとめの単位（次の節）ごとに、`steps[0]` の種別のイベントを時刻順に見る。repeat の「まとめ」と同じく、直前に「数えた」イベントから `collapse_seconds` 以内（ちょうどを含む）のイベントは、その回に含める。数えたイベントごとに、含めたイベントと合わせて 1 件の検知にする。
  - 1 件の検知の長さは `collapse_seconds` 以内になる。
  - 例（`collapse_seconds=300`）: scsi@0 秒・psastor@0.5 秒 → 1 件。scsi@0 秒・psastor@300 秒 → 1 件。scsi@0 秒・psastor@301 秒 → 2 件。scsi@0 秒・psastor@0 秒・scsi@600 秒 → 2 件。
- **repeat の `min_count=1` にしない理由:** repeat の窓は、数えたイベントどうしを `within_minutes` でつなぐので、`within_minutes` を長くすると 1 件の検知が際限なく伸びる。また、「1 回でも起きたら検知」であることを、定義と API（パターンの一覧の `kind`）で明示するためである。今の画面は種類を表示しないので、表示は変えない。
- 定義の検査（`tests/services/test_event_patterns.py`）に、`occurrence` の組み合わせを足す。

### デバイスでまとめる（`subject`）

- `EventPattern` に `subject: Literal["device"] | None = None` を足す。`"device"` のパターンは、まとめの単位をデバイスごとにする。ほかのパターンは今のまま `(vcenter_id, entity_moid)` である。
- **デバイス ID の規則:** `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`（ASCII、128 文字まで）に合うものだけを ID とみなす。診断コマンドの引数の規則（`catalog.py:15`）と同じにし、検知に出た ID をそのまま `esxi.device` に渡せるようにする。PR B では、規則を 1 か所に置いて両方から使う。
- **デバイスの取り出し**（本文から。純関数にして単体テストで固める）:
  1. 本文の先頭が定型文の場合は、「Device」の直後から「has been removed or is permanently inaccessible」の直前までを ID 欄として取り出す。欄の値全体が ID の規則に合えばそれを使い、空白や括弧を含む場合などは不明とする。定型文に当たった時点で判定を終えるので、途中までの ID や後続のデータストア名を拾うことはない。
  2. 1 の文の形に当たらないときは、本文から次の正規表現に合う文字列をすべて探す。ID の規則に合い、小文字にした後の異なる値がちょうど 1 つなら、それを使う（英語以外の本文や、書式が変わった場合、本文が `str(e)` の形の場合に備える）。
     ```
     (?<![A-Za-z0-9._:-])(?:naa|eui|mpx)\.[A-Za-z0-9_.:-]*[A-Za-z0-9_](?=\Z|[\s,;'")\]]|\.(?:\Z|\s)|[^\x00-\x7f])
     ```
     - `naa`・`eui`・`mpx` は大文字と小文字を区別しない。前に ID の文字が続く部分（`ds-naa.…`）は拒む。
     - `naa.a/naa.b` や `naa.a(naa.b)` のように、許可する区切りを挟まず別の候補につながる値は不明とする。
     - ID の終わりとして許すのは、本文の終わり、空白、ASCII の `,;'")]`、空白か本文の終わりが続く句点、ASCII 以外の文字（日本語の本文の「。」「）」など）だけである。ID を続け得る ASCII の記号（`(`・`/`・`+` など）が続くときは、途中までの ID を返さない（拒む）。
     - `t10.` は連結の判定に使い、ID の候補には加えない。t10 の ID は機器の名前を含み、空白を含む表記があると途中までの ID（`t10.ATA`）になり、別のディスクが 1 件にまとまるおそれがあるためである。英語の本文の t10 は 1 番目の規則で取れる。
  3. どちらでも決まらないとき（0 個、または異なる値が 2 個以上）は、デバイスを不明とする。
  - 規則は、境界の例（2026-11-27、21 件）で試し、期待どおりだった。PR B の単体テストにする。
  - まとめのキーには、小文字にした値（ASCII に限るので `lower()` で足りる）を使う。表示には、検知の最初のイベントから取り出した値を使う。
- **デバイスが不明のイベント:** 時刻とホストだけで同じ障害とは断定しない。そのイベント 1 件で 1 件の検知にし、ほかのイベントとまとめない。
- **まとめのキー:** 比べられる形にする（`sorted` で None と文字列が混ざらないように）。
  - デバイスが分かるとき: `(vcenter_id, entity_moid, 0, 小文字のデバイス ID)`
  - 不明のとき: `(vcenter_id, entity_moid, 1, event_id)`。同じイベントの `host` と `object` の行は 1 件にまとまり、ほかのイベントとは分かれる。
  - `subject` の無いパターンは、今のキー `(vcenter_id, entity_moid)` のまま。
- **問い合わせ:** `subject` のあるパターンだけ、`events.message` も読む。ほかのパターンの問い合わせは変えない。本文を読んでも、SQLite の索引の指定（`INDEXED BY`）が効くことを確かめる（`tests/services/test_aggregation_dialects.py:1018` のテストに足す）。

### パターン `pdl`

| 項目 | 値 |
|---|---|
| id | `pdl` |
| 名前 | デバイスの恒久的な喪失（PDL） |
| 種類 | `occurrence` |
| 種別 | `esx.problem.scsi.device.state.permanentloss`・`esx.problem.psastor.device.state.permanentloss` |
| 同じ対象 | ホスト（APD と同じ `_HOST`） |
| まとめ | デバイス（`subject="device"`）、300 秒 |
| 時間幅 | 5 分（`ceil(300 / 60)`） |
| レベル | critical |

- **まとめの幅を 300 秒にする理由:** 2 つの種別が vCenter に何秒の差で届くかを、実機で確かめられていない。`vobd.log` では同じ時刻だが、vCenter への到着や時刻の付け方で差が出るおそれがある。同じホスト・同じデバイスの PDL が 5 分以内に繰り返しても、同じ障害として扱って困らない。広めにしておき、実際に PDL が起きたら PR #405 の道具で時刻差を確かめて直す。
- **兄弟の種別**（`.noopens`・`.withreservationheld`・`.pluggedback`）は、最初の版では使わない。書式を確かめていないためである（6 章）。
- **説明の文面:**「ホストからストレージデバイス（LUN）が恒久的に失われた（PDL）と報告されました。パスが戻るのを待っても回復しません。まずデバイスの状態と、同じデバイスを使うほかのホストを確認してください。」（PR B でレビューする）
- **APD のパターンへの影響:** 種別が重ならないので、APD の 2 パターンの判定は変わらない。PR B で、PDL と APD のイベントが同じホストに混ざっても、それぞれの検知が変わらないことをテストする。

### 検知と応答

- `PatternDetection` に `device_id: str | None` を足す。`subject` の無いパターンでは常に None である。
- `IncidentTimelineDetectedPattern` に、`subject: Literal["device"] | None = None` と `device_id: str | None = None` を足す。既定値付きにし、保存済みのスナップショット（キーが無い形）も読めるようにする。画面の zod（`api/schemas/incidentTimelineView.ts`）にも、どちらも `.nullable().default(null)` で足す。
- **「デバイスを特定できません」を出す規則:** `subject` が `"device"` で `device_id` が null のとき。`subject` が null の検知（ほかのパターン）には何も出さない。画面（PR C）と調査資料（PR B）で同じ規則にする。
- **並べ方:** 今の順（レベル、`last_utc` の新しい順、`pattern_id`、vCenter、moid）の後に、デバイスが不明の検知を先に、デバイス ID、`first_utc`、先頭のイベントの id を足す。スナップショットと調査資料で順が揺れないようにする。
- パターンの一覧の API（`api/schemas/event_patterns.py`）の `kind` に `occurrence` を足し、`subject` を返す。画面の zod（`eventPatterns.ts`）も同じ PR で直す（1 章）。

### 通知

- **`context_key` は今の `{vcenter_id}:{entity_moid}:{pattern_id}` のままにし、デバイスを入れない。** 通知履歴の応答、タイムラインのアラートの行、手順の候補は、今の形を前提に `context_key` を解析する（`alert_eval_common.py` の `parse_event_pattern_context_key`）。自動スナップショットの `trigger_id` は、`context_key` をそのまま（長ければハッシュにして）使う。どれも形を変えると直す箇所が広がるためである。
- **再通知の規則は今のまま変えない。** 同じ vCenter・ホスト・パターンの key で、クールダウンの間に別のデバイスの PDL が起きても、今の規則どおり `fired_at` に吸収し、通知しない。
  - 理由: 最初の版の範囲を絞るためである。最初の通知でホストの PDL は知らされ、調査ではホストのデバイスを一通り確かめるので、受け入れる。再通知する場合の規則は 6 章に残す。
  - この制約は `docs/userguide/alerts.md` に書く（今の説明「間隔内に進んだ終了時刻は…送り直さない」（145 行）と合っているので、文面は足すだけにする）。
- **本文:** key ごとに検知の一覧を持つ形に変える（今は最新の 1 件だけ）。発火・再通知の判定は、今のとおり最新の検知の `last_utc` で行う。本文には、同じ vCenter・ホスト・パターンで評価の範囲にある検知のデバイスを、`first_utc` の古い順に最大 10 件と残りの件数で書く。不明の検知は「デバイスを特定できません（N 件）」とまとめて書く。評価の範囲（既定 1 時間、`settings.py:503`）には通知済みの検知も入るので、見出しは「範囲内で検知したデバイス」とする。

### 調査資料と対応手順

- 調査資料の出力（`incident_timeline_export.py:296-301`）の検知の行に、デバイス（あれば）か「デバイスを特定できません」を足す（上の規則）。
- 対応手順 `pdl` を `BUILTIN_PROCEDURES` に足す。APD の手順（`_APD_STEPS`）を手本にし、次を並べる。
  1. ホストの照合（`esxi.hostname`）
  2. タイムラインで、同じ時間帯にほかのホストでも同じデバイスの PDL が起きていたかを確かめる
  3. 検知に出たデバイス ID を指定して、デバイスの状態を確かめる（`esxi.device`）。ID が拒まれたときは、次の手順のパスの一覧から探す
  4. そのデバイスのパスの状態を確かめる（`esxi.paths`）
  5. ストレージアダプタの状態を確かめる（`esxi.adapters`）

### 範囲外とする影響先

次は、この Issue では変えない。PR B の文書に、制約として書く。

- タイムラインのアラートの行（`incident_timeline_view.py:1523-1535`）と通知履歴は、`context_key` から説明を作るので、デバイスは出ない。
- `TimelineCardIncidentButton` はイベントの id だけをインシデントに写す。検知のデバイスは写さない（イベントの本文には入っている）。
- 手順の候補（`procedures.py:150-155`）は `entity_type == "HostSystem"` でホストを決めるので、種別が NULL の EventEx ではホストが添えられない（APD と同じ既存の制約）。
- 名前での絞り込み（`entity`）はホスト名だけに当たり、デバイス ID では絞れない。

## 3. 範囲

範囲の決め方は、パターンの計画書の 3 章と同じである。`[from - within_minutes, to)` を読み、検知に使ったイベントの少なくとも 1 件が `[from, to)` に入る検知を返す。

まとめは数えたイベントを基点に連鎖するので、期間の始まりより前から続く検知は、読み始める位置によって分かれ方が変わり得る。例（`collapse_seconds=300`、時刻は `from` からの秒）: -310・-200・+50 秒のイベントは、すべて読むと「-310・-200」と「+50」の 2 件（-200 は -310 から 110 秒、+50 は -310 から 360 秒）、-300 秒から読むと「-200・+50」の 1 件になる。期間の中にイベントがある検知だけを返すので、前者は「+50」の 1 件、後者は「-200・+50」の 1 件を返す。パターンの計画書の 3 章と同じく、仕様とする（同じ要求なら同じ結果になる）。

## 4. リスク

- **実際のイベントで対象が入らない:** 実機の PDL のイベントに `objectId` や基底の `host` が入るかは確かめていない。APD と同じく、`host`・`object`・`managedObject` の役割と、種別が NULL で `host-` で始まる `object` の行を見るので、どちらの形でも当たる見込みである。
- **2 つの種別の時刻差が 300 秒を超える:** 1 回の障害が 2 件の検知になる。実際に PDL が起きたら、道具で時刻差を確かめて幅を直す。
- **2 つの種別でデバイスの表記が違う:** 1 回の障害が 2 件の検知になる。大文字と小文字の違いは吸収する。
- **本文の書式が変わる・英語でない:** 1 番目の取り出しに当たらなくても、`naa.`・`eui.`・`mpx.` の ID が 1 つなら取り出せる。t10 の ID や、取り出せないときは、イベントごとに別の検知になる（数は増えるが、見落とさない）。
- **空白を含むデバイス ID:** どちらの規則でも ID とみなさず、不明になる。ESXi は t10 の ID の空白を下線にするので、起きない見込みである。
- **共有のデータストアの PDL:** 同じ LUN を使う全ホストで検知が出て、上限の 20 件を埋め得る。パターンの計画書の 9 章と同じリスクで、総数で切れたことは分かる。
- **兄弟の種別を使わない:** `.withreservationheld` などで PDL が報告される場合は、検知されない。
- **vcsim で確かめられる範囲:** vcsim には `esx.problem.*` のカタログが無い。`PostEvent` で `fullFormattedMessage` を明示した場合と空の場合に、アプリの収集の経路で何が保存されるかは、PR B の vcsim の確認で確かめる（PR #405 で分かったのは、投稿したイベントを道具が読めたことだけである）。vcsim で確かめられるのは、対象の役割と、vcsim が返す本文の形の取り出しだけで、実機の本文の形ではない。

## 5. PR の分け方

### PR A: 本書

本書と、パターンの計画書の 10 章の PDL の行（本書への案内）。PR #405 の後にマージする。

### PR B: 判定・API・通知・調査資料・対応手順・利用者ガイド

- 定義: 種類 `occurrence`、`subject`、パターン `pdl`、定義の検査
- 判定: デバイスの取り出し（純関数）、まとめのキー、`_occurrence`、`device_id`
- 問い合わせ: `subject` のあるパターンだけ本文を読む
- API: `IncidentTimelineDetectedPattern` の `subject` と `device_id`、並べ方、パターンの一覧の `kind` と `subject`
- 画面のスキーマ: `eventPatterns.ts` と `incidentTimelineView.ts` の zod（表示は PR C）
- 通知: key ごとの検知の一覧と本文のデバイスの並び
- 調査資料の行、対応手順 `pdl`、デバイス ID の規則を診断コマンドの引数と共通にすること
- 既存のテストの書き直し:
  - `tests/services/test_event_patterns.py:28` のパターンの数（7 → 8）と、34-39 行の、repeat 以外を sequence とみなす分岐
  - `tests/test_diagnostics_procedures.py:39-48` の表（`pdl` を足す）
  - `tests/test_event_patterns_api.py:236-244` の id の並びと、`patterns[0]` を完全に一致させる比較（`subject` を足す）
  - `tests/services/test_aggregation_dialects.py:1018` の索引のテスト
- 足すテスト（合成データ）:
  - 2 つの種別が同じホスト・同じデバイスで 300 秒以内 → 1 件。ちょうど 300 秒 → 1 件。301 秒 → 2 件
  - 片方の種別だけ → 1 件
  - 同じ時刻に別のデバイス → 2 件
  - デバイスが分かるイベントと不明のイベントが同じ時刻 → 2 件
  - デバイスが不明 → イベントごとに 1 件で、ほかとまとめない
  - 取り出しの境界: 1 番目の規則（下線入りの t10、`mpx.…:L0`）、1 番目の文の形で値が規則に合わない場合（2 番目に進まない）、`str(e)` の形の本文、ID の形の文字列が 1 つ・同じ値が 2 回・異なる値が 2 つ、`ds-naa.…`、末尾の句点、`,`、空の ID、128 文字と 129 文字、空白入りの t10、直後に `(`・`/`・`+`、直後に日本語の「。」「）」
  - 大文字と小文字の違うデバイス ID → 同じデバイス
  - 期間の始まりより前から続く検知（3 章の例の期待値）
  - APD のパターンの検知が、PDL のイベントの有無で変わらない
  - 通知: 同じホストの 2 つのデバイスで通知が 1 件、本文に 2 つのデバイス。クールダウン中に別のデバイスが起きても再通知しない。不明の検知の書き方
  - 保存済みのスナップショット（`subject` と `device_id` のキーが無い形）を、バックエンドの `model_validate` と画面の zod の両方で読める。zod が `occurrence` と `subject` を読める
  - 診断コマンドの引数が下線入りの ID を受け、空白を拒む（今の動きの確認。変更なし）
- vcsim の確認: 2 つの種別を `PostEvent` で投稿し（`fullFormattedMessage` を明示した場合と空の場合）、収集・保存・判定・タイムラインの API までを本物の経路で確かめる（4 章）。
- 文書:
  - CHANGELOG
  - `docs/development/backend.md` の 82 行（一覧の項目に `subject`）と 149 行付近（検知の項目と並び順に `device_id`）
  - `docs/userguide/timeline.md` と `docs/userguide/alerts.md` のパターンの表（142 行付近）に `pdl` と、デバイスでのまとめ方、通知の制約、範囲外とする影響先（画面の表示の説明は PR C で書く）
- PR B と PR C の間は、画面の検知の欄にデバイスが出ない。同じホストの別のデバイスの PDL は、見分けられない 2 枚のカードになる。調査資料と通知の本文にはデバイスが出るので、受け入れる。

### PR C: タイムラインの画面

- 「検知した障害パターン」（`panels/timeline/TimelineHighlights.tsx`）に、デバイスを出す。2 章の規則で「デバイスを特定できません」を出す。
- `docs/userguide/timeline.md` に、画面のデバイスの表示と「デバイスを特定できません」の意味を書く。
- 確かめる観点は `docs/development/frontend.md` の「実装とレビューで確かめること」による。画面のスクリーンショットは `scripts/pr_screenshots/run.py --publish` で撮る。

## 6. 範囲外（後続）

- 兄弟の種別（`.noopens`・`.withreservationheld`）を材料にすること。道具（PR #405）で兄弟の書式も出すようにし、実機で確かめてから決める。
- `.pluggedback` を回復として使うこと（パターンの計画書の「否定」のパターンと同じく、状態が要る）。
- 同じホストで新しいデバイスの PDL が起きたときに、クールダウンの間でも再通知すること。DB の移行は要らず、`last_notified_at` で決められる。例: key の検知のうち `first_utc > last_notified_at` で、そのデバイスに `first_utc <= last_notified_at` の検知が無いものがあれば、新しいデバイスとして通知する。通知すれば `last_notified_at` が進むので、同じデバイスで繰り返し通知しない。
- 2 章の「範囲外とする影響先」に挙げたもの。
- 画面の zod が、知らない `kind` を受け入れるようにすること（種類を足すたびにスキーマを直さなくて済むように）。
- 実際に PDL が起きたあと、道具で時刻差を確かめ、まとめの幅を直すこと。
- NIC のリンクダウンなど、ほかのパターンを `subject` で vmnic ごとにまとめること。
