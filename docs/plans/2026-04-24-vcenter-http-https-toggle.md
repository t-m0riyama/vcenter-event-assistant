# vCenter HTTP/HTTPS切替対応計画

## 目的
- 各 vCenter ごとに `protocol`（`https` / `http`）を保持できるようにする。
- 設定タブの vCenter サブタブで `HTTPS` と `HTTP` を切替・保存可能にする。
- 接続実行時に `protocol` を反映し、`HTTP` でも接続試行する。

## 変更対象
- バックエンドモデル/スキーマ
  - [`/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/db/models.py`](/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/db/models.py)
  - [`/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/api/schemas.py`](/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/api/schemas.py)
  - [`/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/api/routes/vcenters.py`](/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/api/routes/vcenters.py)
- 接続/収集処理
  - [`/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/collectors/connection.py`](/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/collectors/connection.py)
  - [`/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/collectors/events.py`](/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/collectors/events.py)
  - [`/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/collectors/perf.py`](/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/collectors/perf.py)
  - [`/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/services/ingestion.py`](/Users/moriyama/git/vcenter-event-assistant/src/vcenter_event_assistant/services/ingestion.py)
- フロントエンド
  - [`/Users/moriyama/git/vcenter-event-assistant/frontend/src/api/schemas.ts`](/Users/moriyama/git/vcenter-event-assistant/frontend/src/api/schemas.ts)
  - [`/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/settings/VCentersPanel.tsx`](/Users/moriyama/git/vcenter-event-assistant/frontend/src/panels/settings/VCentersPanel.tsx)
- マイグレーション/テスト
  - `alembic/versions/*`（新規 migration 追加）
  - [`/Users/moriyama/git/vcenter-event-assistant/tests/test_vcenters_api.py`](/Users/moriyama/git/vcenter-event-assistant/tests/test_vcenters_api.py)
  - [`/Users/moriyama/git/vcenter-event-assistant/tests/test_vcenter_proxy_connection.py`](/Users/moriyama/git/vcenter-event-assistant/tests/test_vcenter_proxy_connection.py)

## 実装方針
- DBに `protocol` カラムを追加（`NOT NULL`、既存行は `https` で埋める）。
- APIの `VCenterCreate/Update/Read` に `protocol` を追加し、未指定時は `https` 補完で後方互換を維持。
- UIフォーム（新規/編集）に `protocol` セレクタを追加し、`HTTP/HTTPS` を切替可能にする。
- 接続処理で `protocol` に応じて分岐し、`http` でも接続試行を行う。
- 失敗時エラーには protocol/host/port 情報を含めて調査しやすくする。

## データフロー
```mermaid
flowchart LR
uiForm[VCentersPanel protocol選択] --> apiPayload[/api/vcenters payload]
apiPayload --> vcenterModel[VCenter protocol保存]
vcenterModel --> ingestion[Ingestion jobs]
ingestion --> connector[connect_vcenter protocol分岐]
connector --> vcTarget[vCenter endpoint]
```

## 検証方針
- Migration適用後、既存レコードが `https` になっていることを確認。
- API CRUDで `protocol` の保存・更新・返却を確認。
- vCenterサブタブのフォームで `HTTP/HTTPS` 切替と再編集時の保持を確認。
- 接続処理で `protocol` 分岐が呼び出されること、HTTP失敗時に期待エラーとなることを確認。
