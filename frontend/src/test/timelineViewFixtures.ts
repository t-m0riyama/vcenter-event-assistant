/** `tests/test_incident_timeline_view_api.py` が確かめている応答の形に合わせた例。 */
export const VIEW_RESPONSE_EXAMPLE = {
  from_utc: '2026-03-22T00:00:00Z',
  to_utc: '2026-03-22T01:00:00Z',
  anchor_utc: null,
  bucket_seconds: 60,
  overview: [
    {
      bucket_start_utc: '2026-03-22T00:00:00Z',
      event_total: 3,
      event_notable: 1,
      alert: 1,
      metric_breach: 0,
      log_error: 0,
    },
  ],
  items: [
    {
      id: 'event:12',
      kind: 'event',
      timestamp_utc: '2026-03-22T00:10:00',
      end_utc: '2026-03-22T00:12:00',
      level: 'warning',
      title: 'VmPoweredOffEvent',
      detail: 'vm-a was powered off',
      entity_name: 'vm-a',
      entity_type: 'HostSystem',
      vcenter_id: '11111111-1111-1111-1111-111111111111',
      vcenter_name: 'vc-detail',
      score: 55,
      count: 2,
      ref: { event_id: 12, event_type: 'VmPoweredOffEvent' },
    },
    {
      id: 'alert:4',
      kind: 'alert',
      timestamp_utc: '2026-03-22T00:20:00+00:00',
      level: 'critical',
      title: 'CPU 高負荷: 発火',
      count: 1,
      ref: { alert_history_id: 4, alert_rule_name: 'CPU 高負荷', alert_state: 'firing' },
    },
  ],
  truncated: false,
  total_items: 2,
  highlights: {
    first_signal: null,
    top_entities: [
      {
        entity_name: 'vm-a',
        entity_type: 'HostSystem',
        vcenter_id: '11111111-1111-1111-1111-111111111111',
        vcenter_name: 'vc-detail',
        item_count: 2,
        first_seen_utc: '2026-03-22T00:10:00Z',
      },
    ],
    new_event_types: [
      { event_type: 'VmPoweredOffEvent', count: 2, first_seen_utc: '2026-03-22T00:10:00Z', max_score: 55 },
    ],
  },
}
