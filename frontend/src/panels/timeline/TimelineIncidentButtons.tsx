import type { TimelineConfigChange, TimelineDetectedPattern, TimelineViewItem } from '../../api/schemas'
import { IncidentLinkButton } from '../incidents/IncidentLinkDialog'

export function TimelineRowIncidentButton({ item }: { item: TimelineViewItem }) {
  if (item.kind !== 'event' && item.kind !== 'alert') return null
  const id = item.kind === 'event' ? item.ref.event_id : item.ref.alert_history_id
  if (id == null) return null
  const notice = item.count > 1 ? `まとめた ${item.count} 件のうち、先頭の 1 件を追加します` : undefined
  return (
    <IncidentLinkButton
      source={{ kind: item.kind === 'event' ? 'events' : 'alerts', items: [{ id, occurred_at: item.timestamp_utc }] }}
      notice={notice}
    />
  )
}

export function TimelineCardIncidentButton({ card }: { card: TimelineConfigChange | TimelineDetectedPattern }) {
  const items = card.event_ids.slice(0, 20).map((id) => ({
    id,
    occurred_from: card.first_utc,
    occurred_to: card.last_utc,
  }))
  if (items.length === 0) return null
  const notice = card.event_count > items.length ? `${card.event_count} 件のうち、先頭の ${items.length} 件を追加します` : undefined
  return <IncidentLinkButton source={{ kind: 'events', items }} notice={notice} />
}
