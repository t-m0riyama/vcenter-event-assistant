import type { IncidentDetail, IncidentList } from '../api/schemas/incidents'

export const INCIDENT_ID = '11111111-1111-4111-8111-111111111111'
export const SNAPSHOT_ID = '22222222-2222-4222-8222-222222222222'
export const AT = '2026-03-22T00:10:00.123456Z'
export const INCIDENT_TITLE = 'ホスト接続が断続的に切断'
export const INCIDENT_DETAIL: IncidentDetail = {
  id: INCIDENT_ID,
  title: INCIDENT_TITLE,
  status: 'monitoring',
  level: 'error',
  assignee: '担当者',
  started_at: AT,
  resolved_at: null,
  created_by: '担当者',
  updated_by: '担当者',
  created_at: AT,
  updated_at: AT,
  revision: '33333333-3333-4333-8333-333333333333',
  summary: '管理ネットワークを調査中',
  entries: [
    { id: 1, incident_id: INCIDENT_ID, kind: 'note', body: '再発の有無を確認', author: '担当者', created_at: AT, deleted_by: null, deleted_at: null },
    { id: 2, incident_id: INCIDENT_ID, kind: 'note', body: '', author: '担当者', created_at: AT, deleted_by: '管理者', deleted_at: AT },
  ],
  events: [{
    id: 1, incident_id: INCIDENT_ID, event_id: 123, vcenter_id: INCIDENT_ID, vcenter_name: 'demo-vc',
    entity_moid: 'host-1', entity_name: 'demo-esxi', collector_id: 'events', vmware_key: 1234,
    occurred_at: AT, added_at: AT, added_by: '担当者', source_exists: true, event_type: 'HostConnectionLostEvent',
    severity: 'error', notable_score: 50, entity_type: 'HostSystem', user_name: null, message: '接続を失いました',
    user_comment: 'vCenter を確認',
  }],
  alerts: [{
    id: 1, incident_id: INCIDENT_ID, alert_history_id: 13, rule_id: 10, rule_name: '切断の通知', rule_type: 'event_pattern',
    alert_level: 'warning', state: 'firing', context_key: 'demo-esxi', vcenter_id: null, vcenter_name: null,
    entity_moid: null, entity_name: null, occurred_at: AT, added_at: AT, added_by: '担当者', source_exists: false,
  }],
  snapshots: [{
    id: 1, snapshot_id: SNAPSHOT_ID, operator_note: '切断時の保存結果', snapshot_kind: 'manual',
    from_time: '2026-03-22T00:00:00Z', to_time: '2026-03-22T01:00:00Z', created_at: AT, has_result: true,
  }],
}
export const INCIDENT_LIST: IncidentList = {
  items: [{ ...INCIDENT_DETAIL, event_count: 1, alert_count: 1, snapshot_count: 1 }],
  total: 1,
}
