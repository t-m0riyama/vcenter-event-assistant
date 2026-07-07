import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './DigestsPanel.css'

import ReactMarkdown from 'react-markdown'
import { apiGet } from '../../api'
import { rehypePlugins, remarkPlugins } from '../../markdown/gfmSanitizedMarkdownPlugins'
import { parseDigestListResponse, type DigestRead } from '../../api/schemas'
import { formatIsoDateOnlyInTimeZone, formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { toErrorMessage } from '../../utils/errors'
import { downloadTextFile } from '../../utils/downloadTextFile'
import { buildDigestDownloadFilename } from './buildDigestDownloadFilename'
import { digestStatusLabel, resolveDigestEffectiveStatus } from './digestStatusDisplay'
import { getDigestBodyMarkdownForDisplay } from './getDigestBodyMarkdownForDisplay'

/** 1 ページあたりのダイジェスト件数（`GET /api/digests` の `limit`） */
export const DIGEST_LIST_PAGE_SIZE = 50

type LoadState = 'loading' | 'ready' | 'error'
type DigestKindFilter = 'all' | 'daily' | 'weekly' | 'monthly'

const DIGEST_KIND_FILTERS: readonly DigestKindFilter[] = ['all', 'daily', 'weekly', 'monthly']

function SelectedDigestDetail({
  selected,
  formatRange,
  formatDigestInstant,
}: {
  selected: DigestRead
  formatRange: (fromIso: string, toIso: string) => string
  formatDigestInstant: (iso: string) => string
}) {
  const bodyMd = getDigestBodyMarkdownForDisplay(selected)
  const effectiveStatus = resolveDigestEffectiveStatus(selected)
  return (
    <>
      <p className="digests-detail-meta">
        {formatRange(selected.period_start, selected.period_end)} · 作成{' '}
        {formatDigestInstant(selected.created_at)}
      </p>
      <p className="digests-detail-download">
        <button
          type="button"
          className="btn btn--gray"
          onClick={() => {
            downloadTextFile(
              buildDigestDownloadFilename(selected),
              getDigestBodyMarkdownForDisplay(selected),
            )
          }}
        >
          Markdown をダウンロード
        </button>
      </p>
      {selected.llm_model != null && (
        <p className="digest-llm-meta">LLM 要約あり（{selected.llm_model}）</p>
      )}
      {selected.error_message != null && selected.error_message.trim() !== '' && (
        <div className="digest-aux-warning" role="status">
          {selected.error_message}
        </div>
      )}
      {effectiveStatus === 'ok_llm_failed' && (
        <p className="hint digest-status-hint" role="status">
          テンプレート本文は保存済みですが、LLM 要約は生成できませんでした。
        </p>
      )}
      {effectiveStatus === 'error' && (
        <p className="hint" role="status">
          このダイジェストはエラーで保存されています。
        </p>
      )}
      {bodyMd.trim() ? (
        <div className="digest-markdown">
          <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
            {bodyMd}
          </ReactMarkdown>
        </div>
      ) : (
        <p className="hint">（本文なし）</p>
      )}
    </>
  )
}

/**
 * 保存済みダイジェストの一覧・本文（Markdown）を表示するパネル。
 */
export function DigestsPanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [items, setItems] = useState<DigestRead[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [selectedKind, setSelectedKind] = useState<DigestKindFilter>('all')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const latestRequestIdRef = useRef(0)

  const load = useCallback(async () => {
    const requestId = latestRequestIdRef.current + 1
    latestRequestIdRef.current = requestId
    onError(null)
    setLoadState('loading')
    try {
      const q = new URLSearchParams({
        limit: String(DIGEST_LIST_PAGE_SIZE),
        offset: String(offset),
      })
      if (selectedKind !== 'all') q.set('kind', selectedKind)
      const raw = await apiGet<unknown>(`/api/digests?${q.toString()}`)
      const parsed = parseDigestListResponse(raw)
      if (requestId !== latestRequestIdRef.current) return
      setItems(parsed.items)
      setTotal(parsed.total)
      setLoadState('ready')
    } catch (e) {
      if (requestId !== latestRequestIdRef.current) return
      setItems([])
      setTotal(0)
      setLoadState('error')
      onError(toErrorMessage(e))
    }
  }, [offset, onError, selectedKind])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount / offset 変更時の一覧再取得
    void load()
  }, [load])

  const selected = useMemo(
    () => items.find((d) => d.id === selectedId) ?? null,
    [items, selectedId],
  )

  const canPrev = offset > 0
  const canNext = offset + DIGEST_LIST_PAGE_SIZE < total
  const emptyMessage =
    selectedKind === 'all'
      ? '保存済みのダイジェストはありません。'
      : `${selectedKind} の保存済みダイジェストはありません。`

  const formatDigestInstant = useCallback(
    (iso: string) => formatIsoInTimeZone(iso, timeZone, { omitSeconds: true }),
    [timeZone],
  )

  const formatListPeriodStartDate = useCallback(
    (iso: string) => formatIsoDateOnlyInTimeZone(iso, timeZone),
    [timeZone],
  )

  const formatRange = useCallback(
    (fromIso: string, toIso: string) =>
      `${formatDigestInstant(fromIso)} 〜 ${formatDigestInstant(toIso)}`,
    [formatDigestInstant],
  )

  if (loadState === 'loading') {
    return (
      <div className="panel digests-panel">
        <h2>ダイジェスト</h2>
        <p>読み込み中…</p>
      </div>
    )
  }

  if (loadState === 'error') {
    return (
      <div className="panel digests-panel">
        <h2>ダイジェスト</h2>
        <p className="hint">ダイジェストを読み込めませんでした。上部のメッセージを確認してください。</p>
      </div>
    )
  }

  return (
    <div className="panel digests-panel">
      <div className="digests-panel-header">
        <h2>ダイジェスト</h2>
        <button type="button" className="btn btn--gray digests-refresh" onClick={() => void load()}>
          一覧を更新
        </button>
      </div>
      <div className="digests-kind-filter" role="group" aria-label="ダイジェスト種別">
        {DIGEST_KIND_FILTERS.map((kind) => (
          <button
            key={kind}
            type="button"
            className={selectedKind === kind ? 'btn btn--gray is-active' : 'btn btn--gray'}
            aria-pressed={selectedKind === kind}
            onClick={() => {
              setSelectedKind(kind)
              setOffset(0)
              setSelectedId(null)
            }}
          >
            {kind}
          </button>
        ))}
      </div>
      <p className="digests-count-hint">全 {total} 件</p>

      {items.length === 0 ? (
        <p className="hint">{emptyMessage}</p>
      ) : (
        <div className="digests-layout">
          <div className="digests-list-column">
            <div data-testid="digests-list-scroll-region" className="digests-list-scroll">
              <nav aria-label="ダイジェスト一覧">
                <ul className="digests-list">
                  {items.map((d) => {
                    const effectiveStatus = resolveDigestEffectiveStatus(d)
                    return (
                    <li key={d.id}>
                      <button
                        type="button"
                        className={selectedId === d.id ? 'digests-row is-selected' : 'digests-row'}
                        onClick={() => {
                          setSelectedId(d.id)
                        }}
                      >
                        <span className="digests-row-kind">{d.kind}</span>
                        <span className="digests-row-range">
                          {formatListPeriodStartDate(d.period_start)}
                        </span>
                        <span
                          className={`digest-status-badge digest-status-badge--${effectiveStatus}`}
                          title={d.status}
                        >
                          {digestStatusLabel(effectiveStatus)}
                        </span>
                        <span className="digests-row-created">
                          作成 {formatDigestInstant(d.created_at)}
                        </span>
                      </button>
                    </li>
                    )
                  })}
                </ul>
              </nav>
            </div>
            <div className="digests-pager">
              <button
                type="button"
                disabled={!canPrev}
                onClick={() => {
                  setSelectedId(null)
                  setOffset((o) => Math.max(0, o - DIGEST_LIST_PAGE_SIZE))
                }}
              >
                前へ
              </button>
              <button
                type="button"
                disabled={!canNext}
                onClick={() => {
                  setSelectedId(null)
                  setOffset((o) => o + DIGEST_LIST_PAGE_SIZE)
                }}
              >
                次へ
              </button>
            </div>
          </div>

          <div className="digests-detail digests-detail--sticky">
            {selected ? (
              <SelectedDigestDetail
                selected={selected}
                formatRange={formatRange}
                formatDigestInstant={formatDigestInstant}
              />
            ) : (
              <p className="hint">左の一覧からダイジェストを選んでください。</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
