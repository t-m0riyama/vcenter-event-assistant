# タイムラインの対象を moid で絞り込み、数える

最終更新: 2026-11-23（計画）

[イベントの対象を正しく保存する計画](2026-11-23-event-entities.md)（Issue #347）の 7 章に挙げた後続の作業である。

本書の用語は、その計画書に合わせる。vCenter の管理対象を一意に指す ID（`host-10` のような値）を **moid** と呼び、出来事が指す管理対象を **対象** と呼ぶ。コードの場所は、バックエンドを `src/vcenter_event_assistant/` から、画面を `frontend/src/` から書く。行番号は、本書を書いた時点の main のものである。

## 進捗

| PR | 内容 | 状態 |
|---|---|---|
| A | 本書 | マージ済み [PR #357](https://github.com/t-m0riyama/vcenter-event-assistant/pull/357) |
| B | API（要求の `entity_moid`、moid での絞り込み、「影響の大きい対象」の数え方、通知履歴の `entity_moid`） | レビュー中 |
| C | 画面（URL、クリックでの絞り込み、他のタブからのリンク） | 未着手 |

各 PR は単独でマージでき、テストが通る状態にする。

## Context

タイムライン（`src/vcenter_event_assistant/services/incident_timeline_view.py`。以下、この章と次の章の行番号はこのファイルのもの）は、対象を名前の文字列でしか扱っていない。

- **対象の絞り込み:** 要求の `entity` は、名前の部分一致（大文字と小文字は区別しない）である。当てる箇所は 5 つある。
  - イベント: `entity_name` に当てる（`_event_filters`、846 行）。直前の期間の判定（956 行）も、この関数を使う。
  - アラート: 対象を解決したあとの名前に当てる（1040 行）。
  - メトリクス: 系列を選ぶ段で、名前に当てる。名前が空なら moid に当てる（1172-1191 行）。区間を作ったあとで、区間の名前にもう一度当てる（1338-1343 行）。
  - ログ: `host` に当てる（`_log_filters`、1420-1422 行）。
- **影響の大きい対象:** `top_entities`（594 行）は、`(vcenter_id, entity_name)` ごとに件数を足す。

そのため、次のことが起きる。

- 同じ名前の別の対象（フォルダの違う同名の VM など）が混ざる。部分一致なので、`web-1` で絞ると `web-10` も入る。
- 名前を変えた対象は、名前ごとに別の対象として数えられる。

Issue #347 で、イベント（`events.entity_moid`、PR #354）にも moid が入るようになった。メトリクス（`metric_samples.entity_moid`）と、メトリクスのアラート（`context_key` が `{vcenter_id}:{entity_moid}`）は、もともと moid を持つ。そこで、クリックで対象を選ぶ操作と「影響の大きい対象」の数え方を、moid で行う。

決めたこと:
- 「影響の大きい対象」や行の「この対象で絞る」を押したときは、vCenter と moid の完全一致で絞る。URL にも moid を載せる。手で入力する欄は、今までどおり名前の部分一致のままにする。
- moid を持たない行は、名前で拾う。対象になるのは、PR #354 より前に保存したイベントと、ホスト名しか持たないログである。
  - 絞り込み: 同じ vCenter で、名前が完全一致すれば含める。
  - 「影響の大きい対象」: 同じ vCenter で、同じ名前の moid の対象がちょうど 1 つなら、そこに合算する。無いか 2 つ以上なら、名前だけの対象として別に数える。

## 1. 前提（コードで確かめたこと）

### 出来事ごとの対象の持ち方

| 種別 | 名前 | 種別名 | moid | 作る場所 |
|---|---|---|---|---|
| イベント | `events.entity_name` | `events.entity_type`（`HostSystem` など） | `events.entity_moid`（PR #354 より前の行は NULL）。一覧の SELECT（885-896 行）は、この列を読んでいない | 916-922 行。`ref` に moid は入れていない。まとめるキー（`merge_key`、921 行）は `("event", event_type, entity_name, vcenter_id, level)` で、moid を含まない |
| アラート（`metric_threshold`） | メトリクスの最新の名前で解決する。解決できなければ None | 同左 | `context_key` から取り出す。旧形式の key は moid だけで、`vcenter_id` は None になる（1076-1077 行） | 1054-1094 行。`ref["entity_moid"]` に入れる |
| アラート（`event_score`） | 無し | 無し | 無し | 対象を持たない |
| メトリクスの超過区間 | 区間の中の最新の名前。無ければ moid（1380 行） | `metric_samples.entity_type` | `metric_samples.entity_moid` | 1370-1392 行。`ref["entity_moid"]` に入れる |
| ログ | `log_records.host`（接続先の表記。FQDN・短い名前・IP のどれか） | `host`（固定。120-122 行） | 無し | 1485-1497 行 |

- ログは、ホスト名を正規化しない（1436-1439 行）。FQDN と短い名前は、同じホストとみなさない。本書でも、この方針は変えない。
- `IncidentTimelineItemRef` には、すでに `entity_moid` がある（`api/schemas/incident_timeline_view.py:132`）。
- `top_entities` は、まとめたあとの行で数える（822 行）。名前の無い行は数えない（609 行）。

### メトリクスの問い合わせと索引

- 系列を選ぶ段（1172-1191 行）は、わざと系列の索引 `(vcenter_id, entity_moid, metric_key, sampled_at)` を避けている（`entity_moid || ''`、1186-1191 行。列の順の注意は 1222-1223 行）。
- SQLite では、`metric_samples` を読む問い合わせを、vCenter・指標・期間の被覆索引に固定する（`pin_metric_covering_index`、Issue #334）。この被覆索引は SQLite にだけあり、`entity_moid` を含む（`db/models.py:186-194`）。

### 要求と保存

- 要求は `IncidentTimelineViewRequest`（`api/schemas/incident_timeline_view.py:47`）で、`extra="forbid"` である。`entity` は最大 256 文字で、`events.entity_name` の上限（1024 文字、`db/models.py:60`）より短い。
- スナップショットは、要求を `view_request` として保存する。読むときは `IncidentTimelineSavedViewRequest`（`extra="ignore"`）を使う。項目を足しても、保存済みの行はそのまま読める。
- 通知履歴の応答 `AlertHistoryRead`（`api/schemas/alerts.py:76-92`）は、`rule_type`・`context_key`・`vcenter_id`・`entity_name` を持つが、moid は持たない。

### 画面

- 条件は URL のハッシュと 1 対 1 に対応する（`frontend/src/routing/timelineHash.ts`）。今は `entity` だけを持つ。読めない値は既定に戻さず、issue として返す（105-108 行）。`vcenter` が UUID の形でなければ、vCenter は空になる（128-133 行）。
- 絞り込みの操作は、どちらも `filterByEntity(name, vcenterId)`（`frontend/src/hooks/useTimelineViewController.ts:464`）を呼ぶ。
  - 「影響の大きい対象」（`frontend/src/panels/timeline/TimelineHighlights.tsx:60`）。React の key は `${vcenter_id}|${entity_name}` である（56 行）。
  - 行の「この対象で絞る」（`frontend/src/panels/timeline/TimelineItemList.tsx:230`）。
- 対象の入力欄は、待ち時間のあとで条件に反映する。整えた入力が `conditions.entity` と同じなら何もしない（`useTimelineViewController.ts:186-193`）。
- 条件を変える箇所は、ほかに次のものがある。
  - vCenter の選択（`setVcenterId`、440 行）
  - 対象の解除（`clearEntity`、469 行）
  - スナップショットの条件の適用（`applySnapshotConditions`、481 行）
- 要求は `buildViewRequest`（`frontend/src/panels/timeline/timelineModel.ts:140`）で作り、保存済みの要求は `conditionsFromViewRequest`（同 120 行）で条件に戻す。要求の型は手書きである（`frontend/src/api/schemas/incidentTimelineView.ts:111`）。
- チャットに渡す前の条件の表示は `narrowedConditions`（`frontend/src/panels/timeline/TimelinePanel.tsx:252`）で作る。
- 他のタブの「タイムラインで見る」は、名前と vCenter を渡す。リンクは `timelineHash.ts` の `timelineEntryHash`（214-235 行）で作る。
  - イベント（`frontend/src/panels/events/EventsPanel.tsx:221`）
  - 通知履歴（`frontend/src/panels/alerts/AlertHistoryPanel.tsx:251`）
  - 概要（`frontend/src/panels/summary/SummaryPanel.tsx`。要注目イベントは 182 行、CPU とメモリの高負荷ホストは 288 行と 334 行。高負荷ホストの行は `entity_moid` を持つ）
- タイムラインには CSV のエクスポートが無い。通知の本文と自動スナップショットは、対象を指定しない。チャットに渡すのは期間と vCenter だけである。

## 2. API の設計

### 要求

- `IncidentTimelineViewRequest` に `entity_moid: str | None`（最大 256 文字。前後の空白を除き、空なら None）を足す。
- `entity_moid` を指定するときは、`vcenter_id` も必要にする。無ければ 422 にする。moid は vCenter の中でしか一意でないためである。
- `entity` の上限を 1024 文字に広げる（`events.entity_name` と同じ）。完全一致で名前を渡すと、長い名前の対象で 422 になるためである。
- `IncidentTimelineSavedViewRequest` にも `entity_moid: str | None = None` を足す。

### 内部の条件（`_Scope`）

`_Scope` に `entity_moid: str | None` を足す。`entity_moid` を指定したときは、1 章の 5 つの部分一致をすべて止め、次の表の条件に替える。`entity` は、moid を持たない行を拾うための名前としてだけ使い、イベントとログにだけ当てる。メトリクスとアラートには当てない（名前を変えた対象が落ちるため）。

| 種別 | 含める行 |
|---|---|
| イベント | `vcenter_id` と `entity_moid` が一致する行。加えて、`entity` があれば、`entity_moid` が NULL で名前が一致する行 |
| アラート（`metric_threshold`） | SQL で `context_key = '{vcenter_id}:{entity_moid}'` に絞る。旧形式の key（vCenter が分からない）は含めない。738-740 行のコメントと `_limit_message` の「対象の絞り込みでは行数が減らない」という案内も直す |
| アラート（`event_score`） | 含めない（今も、対象で絞ると名前が無いので外れる） |
| メトリクス | サンプル単位で `vcenter_id = ? AND entity_moid = ?` を条件に足す。moid は系列のキーなので、サンプル単位で絞っても区間は変わらない。系列を選ぶ段（1172-1191 行）と区間の名前での絞り込み（1338-1343 行）は使わない。被覆索引への固定はそのまま残す |
| ログ | `vcenter_id` が一致し、`entity` があれば `host` が一致する行。`entity` が空なら含めない |

- 名前の一致は、大文字と小文字だけを無視した完全一致にする。両辺を SQL の `lower()` で揃える（`lower(column) = lower(:name)`）。Python で引数を小文字にすると、SQLite の `lower`（ASCII だけを変える）とずれるためである。補助関数 `equals_case_insensitive` を `services/sql_like.py` の `contains_case_insensitive` の隣に置く。どちらの書き方でも、`entity_name` と `host` の索引は使わず、vCenter と期間の索引で行を絞る（今と同じ）。
- 直前の期間（新しいイベント種別の判定）にも、同じ条件をかける。
- `entity_moid` を指定しないときの絞り込み（`entity` の部分一致）は変えない。

### 行の moid とまとめ方

- イベントの一覧の SELECT に `EventRecord.entity_moid` を足し、行の `ref` に入れる（NULL なら入れない）。
- イベントのまとめるキーに moid を足す。足さないと、同名で moid の違う対象の連続したイベントが 1 行にまとまる。そうなると、`ref` には最初の行の moid しか残らず、件数も別の対象に付く。
- moid を対象のキーとして使うのは、`vcenter_id` のある行だけにする。旧形式の key のアラートは、`ref["entity_moid"]` に `context_key` がそのまま入り、`vcenter_id` が None なので、moid を持たない行として扱う。

### 「影響の大きい対象」

`IncidentTimelineTopEntity` に `entity_moid: str | None = None` を足す。`top_entities` は、その応答の行（`sources` の選択、期間、vCenter の指定、省略された種別を反映した、まとめたあとの行）だけを見て、次の順で数える。

1. `vcenter_id` と moid を持つ行は、`(vcenter_id, entity_moid)` ごとに件数を足す。
   - その対象の行に出た名前を、名前の集まりとして覚える。メトリクスの区間で名前の代わりに入った moid（1380 行）と、名前を解決できなかったアラート（名前が None）は、集まりに入れない。
   - 名前の無い行も数える（今は名前の無い行を数えない。moid の対象では、名前が無くても対象は決まる）。
2. moid を持たない行（古いイベント、ログ、旧形式の key のアラート）は、名前の無い行を今までどおり数えない。名前のある行は、同じ vCenter で、名前（大文字と小文字を無視）がその集まりに入る moid の対象を探す。
   - ちょうど 1 つなら、そこに足す。
   - 無いか 2 つ以上なら、`(vcenter_id, 名前)` の対象として別に数える。2 つ以上のときは、どれか 1 つに寄せると取り違えるので寄せない。
3. 表示する名前は、moid の対象なら最新の名前にする。
   - 最新は、行の終わりの時刻（まとめた行やメトリクスの区間は `end_utc`、無ければ `timestamp_utc`）が最も遅い行で決める。同じ時刻なら、種別の順（`entry_sort_key` と同じ）と元レコードの id が大きいほうにする。
   - 名前の集まりが空なら、moid を表示名にする（`entity_name` は必須のため）。
4. `entity_type` は、moid を持つ行の値を優先する（ログの `host` より `HostSystem` を出す）。
5. 件数の数え方（ログはまとめた行を 1 件、ほかは `count`）は変えない。
6. 並べ方は、件数・最初の時刻・名前・vCenter の順に、最後のキーとして moid を足す。
7. 名前の比較は Python の `str.lower` で行う。SQLite では、ASCII 以外の文字で SQL の絞り込みと結果が分かれ得る（今の `entity_matches`、445 行も同じ）。

`entity_moid` を指定しない要求でも、数え方はこの規則に変わる。既存のテスト（`tests/test_incident_timeline_view_api.py:465`、`775`、`1545` など）は moid の無いイベントなので、名前だけの対象のまま結果は変わらない。

### 通知履歴

- `AlertHistoryRead` に `entity_moid: str | None = None` を足す。値は、`metric_threshold` のルールで、`context_key` が新形式（`{vcenter_id}:{entity_moid}`）のときだけ入れる。今の `vcenter_id` を取り出す処理と同じ箇所で取り出す。

### 範囲外

- 手で入力する欄で moid を受け付けること。
- ログのホスト名と、イベント・メトリクスの名前を、FQDN と短い名前で突き合わせること。
- チャットに渡すタイムライン（`services/chat/chat_incident_timeline.py`）。画面のタイムラインとは別に作っており、対象での絞り込みを持たない。

## 3. 画面の設計

- **URL:** ハッシュに `entity_moid` を足す。`vcenter` が無いか読めないときは、moid を捨て、ほかの読めない値と同じく issue を返す。
- **クリックで絞る:**
  - 「影響の大きい対象」は、名前と vCenter に加えて `TopEntity.entity_moid` を渡す。
  - 行の「この対象で絞る」は、名前と vCenter に加えて `ref.entity_moid` を渡す。
  - どちらも、vCenter の無い行の moid は渡さない。moid が無い対象（名前だけの対象、ログの行）は、今までどおり名前の部分一致で絞る。
- **入力欄:**
  - 対象の欄には名前を出す。moid で絞っているあいだは、そのことが分かる印（例:「moid で一致」と moid を出す）を添える。
  - 利用者が欄を編集したら、「編集した」の印を持ち、待ち時間のあとで `entity` と一緒に moid を外す。元の名前に書き戻しても外す。onChange で即座に外すと、古い名前の部分一致で余分な要求が 1 回出るので、そうしない。
- **moid を外すほかの操作:**
  - vCenter の選択を変えたとき（`setVcenterId`）
  - 対象を解除したとき（`clearEntity`）
  - スナップショットの条件を適用するとき（`applySnapshotConditions`）。保存済みの要求に `entity_moid` があれば、それに置き換える。
- **要求の守り:** `buildViewRequest` は、vCenter が無ければ moid を送らない。
- **他のタブからのリンク:** イベント・通知履歴・概要の「タイムラインで見る」は、moid が分かれば `timelineEntryHash` に渡す。
  - イベントと概要の要注目イベントは `EventRead.entity_moid`（PR #355）を、通知履歴は `AlertHistoryRead.entity_moid`（PR B）を使う。
  - 概要の高負荷ホストは、行が持つ `entity_moid` を使う。
- **型とスキーマ:** 次の型とスキーマに `entity_moid` を足す。サーバは null を返し得るので、どれも nullish にする。
  - zod のスキーマ（`frontend/src/api/schemas/incidentTimelineView.ts`）の `TopEntity` と保存済みの要求、通知履歴の型
  - 手書きの要求の型（同 111 行）、`buildViewRequest`、`conditionsFromViewRequest`
- **チャットへの受け渡しの表示:** `narrowedConditions` は、moid で絞っているときも「対象」と出す。

## 4. PR の分け方

### PR A: 本書

- 本書を足す。
- [イベントの対象の計画書](2026-11-23-event-entities.md) の進捗の表を直す（PR C2 をマージ済みにする）。

### PR B: API

- 2 章のとおり。テストは `tests/test_incident_timeline_view_api.py` などの既存の書き方に倣う。
- 画面は、単独でマージしても壊れないよう、次の 2 点だけを直す。
  - 「影響の大きい対象」の React の key に moid を入れる（`TimelineHighlights.tsx:56`）。同名で moid の違う対象が別々に返るので、key が重なるためである。
  - zod のスキーマに、`TopEntity.entity_moid` と `AlertHistoryRead.entity_moid` を省略可で足す。
- CI: moid での絞り込みのテストを、PostgreSQL のジョブ（`.github/workflows/ci.yml` の `auth-postgres`）でも流す。今のジョブと同じく、ファイル名と `-k` の条件で選ぶ。
- 文書:
  - `docs/userguide/timeline.md`（「影響の大きい対象」の数え方）
  - `docs/development/backend.md`（要求の項目と、通知履歴の `entity_moid`）
  - CHANGELOG

### PR C: 画面

- 3 章のとおり。vitest のテストを足す。
- 文書:
  - `docs/userguide/timeline.md`（「この対象で絞る」と「影響の大きい対象」を押したときの動き、他のタブからのリンク）
  - CHANGELOG

## 5. 確認方法

- PR B
  - 同じ名前の 2 つの VM（moid が違う）のイベント・メトリクス・アラートが、moid で絞ると混ざらないこと。続けて起きたイベントも、1 行にまとまらないこと。
  - 名前を変えた対象が、「影響の大きい対象」で 1 つにまとまり、最新の名前で出ること。
  - moid を持たない古いイベントとログが、名前の完全一致で絞り込みに入り、「影響の大きい対象」で moid の対象に合算されること。同じ名前の moid の対象が 2 つあるときは、合算されないこと。
  - 名前を解決できなかったメトリクスのアラートが、moid の対象として数えられること。旧形式の key のアラートは moid で数えないこと。
  - `entity_moid` を指定して `vcenter_id` が無いと、422 になること。
  - `entity_moid` を指定しないときの絞り込みの結果が変わらないこと（既存のテストがそのまま通る）。
  - SQLite と PostgreSQL の両方で通ること。
- PR C
  - クリックで絞ると、URL に moid が載り、読み直しても同じ条件になること。
  - 欄を編集すると moid が外れること。元の名前に書き戻しても外れること。vCenter を変えたとき、対象を解除したときも外れること。
  - 他のタブからのリンクで、moid が渡ること。
  - スナップショットの条件を適用すると、保存済みの moid に置き換わること。

## 6. リスク

- **ログの取り違えと取りこぼし:** ログは moid を持たず、名前の完全一致で拾う。同じ vCenter で、同じホスト名の別のホストはふつう無いので、取り違えは起きにくい。名前の表記が違う（FQDN と短い名前、IP）ログは拾えない。今の部分一致より拾う範囲が狭くなるので、利用者向けの文書に書く。
- **古いイベントの取り違え:** moid を持たない古いイベントは、名前の完全一致で拾う。同じ名前の別の対象の行も入り得る。保持期間（既定 7 日）が過ぎれば、古い行は無くなる。
- **合算の範囲:** 「同じ名前の moid の対象がちょうど 1 つ」は、その応答の行の中で判定する。`sources` の選択、期間、vCenter の指定、省略された種別によって、合算の結果が変わる。期間内に出来事の無い同名の対象があっても、それとは区別できない。
- **件数と絞り込みの結果の食い違い:** 次の 2 つは決めたとおりの動きで、新しい規則は足さない。利用者向けの文書に書く。
  - 名前を変えた対象: 古い名前の moid の無い行は合算されるが、押すと最新の名前の完全一致で絞るので、一覧には入らない。
  - 同じ名前の moid の対象が 2 つ以上: moid の無い行は合算されないが、押すと名前の完全一致で絞るので、一覧には入る。
- **初めて出たイベント種別:** moid で絞り、`entity` が空のとき、直前の期間の moid の無い行は拾われない。直前の期間は古く、moid の無い行が多いので、「初めて出たイベント種別」が実際より多く出ることがある。画面からのクリックではかならず名前も渡すので、起きるのは URL を手で書いたときなどに限られる。
