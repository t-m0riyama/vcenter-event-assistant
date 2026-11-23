import { useEffect, useId, useState } from 'react'

import { ApiError } from '../../api'
import { getInventoryImpact } from '../../api/inventory'
import type { InventoryImpactResponse } from '../../api/schemas'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'

const relationLabels = {
  cluster: 'クラスタ',
  hosts: 'ホスト',
  vms: 'VM',
  datastores: 'データストア',
  networks: 'ネットワーク',
} satisfies Record<InventoryImpactResponse['groups'][number]['relation'], string>

const changeLabels: Record<string, string> = {
  vm_host: 'VM とホスト',
  host_cluster: 'ホストとクラスタ',
  vm_datastore: 'VM とデータストア',
  host_datastore: 'ホストとデータストア',
  vm_network: 'VM とネットワーク',
  host_network: 'ホストとネットワーク',
}

const entityTypeLabels: Record<string, string> = {
  HostSystem: relationLabels.hosts,
  VirtualMachine: relationLabels.vms,
  ClusterComputeResource: relationLabels.cluster,
  Datastore: relationLabels.datastores,
  Network: relationLabels.networks,
  DistributedVirtualPortgroup: relationLabels.networks,
  OpaqueNetwork: relationLabels.networks,
}

type Change = NonNullable<InventoryImpactResponse['changes']>['items'][number]

/** 同じ観測の開始と終了を、応答順で一対一に対応させる。 */
function combineChanges(changes: readonly Change[]) {
  const byObservation = new Map<string, { opened: number[]; closed: number[] }>()
  changes.forEach((change, index) => {
    const key = JSON.stringify([change.kind, change.at])
    const group = byObservation.get(key) ?? { opened: [], closed: [] }
    group[change.action].push(index)
    byObservation.set(key, group)
  })
  const pairs = new Map<number, { closed: Change; opened: Change }>()
  const pairedLater = new Set<number>()
  for (const { opened, closed } of byObservation.values()) {
    for (let i = 0; i < Math.min(opened.length, closed.length); i++) {
      pairs.set(Math.min(opened[i], closed[i]), { closed: changes[closed[i]], opened: changes[opened[i]] })
      pairedLater.add(Math.max(opened[i], closed[i]))
    }
  }
  return changes.flatMap((change, index) => {
    if (pairedLater.has(index)) return []
    const pair = pairs.get(index)
    const relation = changeLabels[change.kind] ?? change.kind
    const otherType = pair?.opened.other.entity_type
    const label = otherType ? (entityTypeLabels[otherType] ?? relation) : relation
    const text = pair
      ? `${label}: ${pair.closed.other.name} → ${pair.opened.other.name}`
      : `${change.other.name}（${relation}の関係が${change.action === 'opened' ? '開始' : '終了'}）`
    return [{ index, at: change.at, text }]
  })
}

const INLINE_ITEM_LIMIT = 5

function statusMessage(impact: InventoryImpactResponse, timeZone: string) {
  const { status, recorded_since: since, observed_before: before, observed_after: after } = impact
  const previous = before ? formatIsoInTimeZone(before, timeZone) : '直前の観測なし'
  const next = after ? formatIsoInTimeZone(after, timeZone) : '直後の観測なし'
  switch (status) {
    case 'ok':
      return null
    case 'not_recorded':
      return since
        ? `この時点の関係は記録されていません（記録は ${formatIsoInTimeZone(since, timeZone)} から）。`
        : <>まだ関係を収集していません。<a href="#/settings/vcenters">設定の vCenter 一覧</a>で収集状態を確認できます。</>
    case 'unknown_target':
      return 'この対象の関係の記録がありません。'
    case 'unsupported_type':
      return 'この種類の対象の影響範囲は出せません。'
    case 'absent_at_time':
      return `この時点の観測では、この対象は見えていませんでした（直前: ${previous}、直後: ${next}）。`
    case 'stale':
      return before && after
        ? `この時点の前後は ${previous} と ${next} に観測しています。その間の変化は反映していません。`
        : `この時点の前後の観測（${previous}・${next}）。その間の変化は反映していません。`
  }
}

type ImpactPeriod = { from: string; to: string; defaultAt: string; anchor: string | null }
type ImpactTime = 'default' | 'start' | 'end'
type ImpactTargetProps = {
  vcenterId: string
  entityMoid: string
  timeZone: string
  onFilterEntity: (name: string, vcenterId: string, moid: string) => void
}

type ReadyPeriod = ImpactPeriod & Pick<ImpactTargetProps, 'vcenterId' | 'entityMoid'>

export function TimelineImpactSection({
  period, timelineFailed = false, vcenterId, entityMoid, timeZone, onFilterEntity,
}: ImpactTargetProps & { period: ImpactPeriod | null; timelineFailed?: boolean }) {
  const [lastReady, setLastReady] = useState<ReadyPeriod | null>(null)
  const [selection, setSelection] = useState<ImpactTime>('default')
  const headingId = useId()
  // 既定の時刻と同じ時刻に起点を付けた場合も、既定の表示へ戻す。
  const defaultChanged = lastReady?.defaultAt !== period?.defaultAt || lastReady?.anchor !== period?.anchor
  // 再集計中は直前の時点と結果を保つ。
  if (period && (lastReady?.from !== period.from || lastReady.to !== period.to ||
    defaultChanged || lastReady.vcenterId !== vcenterId || lastReady.entityMoid !== entityMoid)) {
    setLastReady({ ...period, vcenterId, entityMoid })
    if (defaultChanged) setSelection('default')
  }
  const at = lastReady && { default: lastReady.defaultAt, start: lastReady.from, end: lastReady.to }[selection]
  const failure = timelineFailed ? 'タイムラインを読み込めなかったため、影響範囲を出せません。' : null

  return (
    <section className="timeline-impact" aria-labelledby={headingId}>
      <div className="timeline-impact__head">
        <h3 id={headingId} className="timeline-section-title">影響範囲</h3>
        <label>
          時点
          <select
            aria-label="影響範囲の時点"
            disabled={!period}
            value={selection}
            onChange={(e) => setSelection(e.target.value as ImpactTime)}
          >
            <option value="default">既定（起点・最初の兆候）</option>
            <option value="start">期間の始まり</option>
            <option value="end">期間の終わり</option>
          </select>
        </label>
      </div>
      <div className="timeline-impact__content" aria-live="polite">
        {lastReady && at ? (
          <ImpactResult
            key={JSON.stringify([lastReady.vcenterId, lastReady.entityMoid, at, lastReady.from, lastReady.to])}
            {...lastReady}
            at={at}
            timeZone={timeZone}
            onFilterEntity={onFilterEntity}
            failure={failure}
          />
        ) : failure ? (
          <p className="hint" role="status">{failure}</p>
        ) : (
          <p className="hint">タイムラインの読み込み後に影響範囲を取得します。</p>
        )}
      </div>
    </section>
  )
}

function ImpactResult({
  vcenterId, entityMoid, from, to, at, timeZone, onFilterEntity, failure,
}: ImpactTargetProps & { from: string; to: string; at: string; failure: string | null }) {
  const [result, setResult] = useState<{ impact: InventoryImpactResponse } | { error: string } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    // StrictMode の片付けが先に走った要求も送らない。
    void Promise.resolve().then(async () => {
      if (signal.aborted) return
      try {
        const impact = await getInventoryImpact({ vcenter_id: vcenterId, entity_moid: entityMoid, at, from, to }, signal)
        if (!signal.aborted) setResult({ impact })
      } catch (e) {
        if (signal.aborted) return
        setResult({
          error: e instanceof ApiError && e.status === 404
            ? 'この vCenter は登録されていません。'
            : '影響範囲を読み込めませんでした。',
        })
      }
    })
    return () => controller.abort()
  }, [vcenterId, entityMoid, at, from, to])

  if (failure) return <p className="hint" role="status">{failure}</p>
  if (!result) return <p className="hint">影響範囲を読み込み中…</p>
  if ('error' in result) return <p className="hint" role="status">{result.error}</p>

  const { impact } = result
  const message = statusMessage(impact, timeZone)
  const { changes } = impact

  return (
    <>
      <p className="hint">
        {impact.target.name} の関係（<time dateTime={impact.at}>{formatIsoInTimeZone(impact.at, timeZone)}</time>）
      </p>
      {message && <p className="timeline-impact__notice" role="note">{message}</p>}
      {impact.groups.length > 0 && (
        <div className="timeline-impact__groups">
          {impact.groups.map(({ relation, items, total }) => {
            const title = `${relationLabels[relation]}（${total} 件）`
            const list = total > 0 && (
              <ul>
                {items.map((item) => (
                  <li key={item.moid}>
                    <button
                      type="button"
                      className="btn btn--gray timeline-impact__filter"
                      aria-label={`${item.name} で絞る`}
                      onClick={() => onFilterEntity(item.name, vcenterId, item.moid)}
                    >
                      {item.name}
                    </button>
                    {item.removed && <span>（現在は見えない）</span>}
                  </li>
                ))}
                {total > items.length && <li>ほか {total - items.length} 件</li>}
              </ul>
            )
            return items.length > INLINE_ITEM_LIMIT ? (
              <details key={relation} className="timeline-impact__group">
                <summary><h4>{title}</h4></summary>
                {list}
              </details>
            ) : (
              <div key={relation} className="timeline-impact__group">
                <h4>{title}</h4>
                {list}
              </div>
            )
          })}
        </div>
      )}
      {changes && (
        <details className="timeline-impact__changes">
          <summary>期間中の変化（関係の開始・終了 {changes.total} 件）</summary>
          {changes.total > 0 ? (
            <ul>
              {combineChanges(changes.items).map(({ at, text, index }) => (
                <li key={index}>
                  <time dateTime={at}>{formatIsoInTimeZone(at, timeZone)}</time>
                  {'　'}{text}
                </li>
              ))}
              {changes.total > changes.items.length && <li>ほか {changes.total - changes.items.length} 件</li>}
            </ul>
          ) : <p className="hint">記録された変化はありません。</p>}
        </details>
      )}
      <p className="hint">
        最後の収集 {impact.last_success_at ? formatIsoInTimeZone(impact.last_success_at, timeZone) : '未収集'}。
        観測の時刻は実際の変化から最大で収集の間隔だけずれることがあります。
      </p>
    </>
  )
}
