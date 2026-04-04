import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { apiGet } from '../../api'
import { rehypePlugins, remarkPlugins } from '../../markdown/gfmSanitizedMarkdownPlugins'
import { parseDigestListResponse, type DigestRead } from '../../api/schemas'
import { formatIsoDateOnlyInTimeZone, formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { toErrorMessage } from '../../utils/errors'
import { downloadTextFile } from '../../utils/downloadTextFile'
import { buildDigestDownloadFilename } from './buildDigestDownloadFilename'
import { getDigestBodyMarkdownForDisplay } from './getDigestBodyMarkdownForDisplay'

/** 1 ページあたりのダイジェスト件数（`GET /api/digests` の `limit`） */
export const DIGEST_LIST_PAGE_SIZE = 50

type LoadState = 'loading' | 'ready' | 'error'

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
      {selected.status === 'error' && (
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
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('loading')

  const load = useCallback(async () => {
    onError(null)
    setLoadState('loading')
    try {
      const q = new URLSearchParams({
        limit: String(DIGEST_LIST_PAGE_SIZE),
        offset: String(offset),
      })
      const raw = await apiGet<unknown>(`/api/digests?${q.toString()}`)
      const parsed = parseDigestListResponse(raw)
      setItems(parsed.items)
      setTotal(parsed.total)
      setLoadState('ready')
    } catch (e) {
      setItems([])
      setTotal(0)
      setLoadState('error')
      onError(toErrorMessage(e))
    }
  }, [offset, onError])

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
      <p className="digests-count-hint">全 {total} 件</p>

      {items.length === 0 ? (
        <p className="hint">保存済みのダイジェストはありません。</p>
      ) : (
        <div className="digests-layout">
          <div className="digests-list-column">
            <div data-testid="digests-list-scroll-region" className="digests-list-scroll">
              <nav aria-label="ダイジェスト一覧">
                <ul className="digests-list">
                  {items.map((d) => (
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
                        <span className="digests-row-status">{d.status}</span>
                        <span className="digests-row-created">
                          作成 {formatDigestInstant(d.created_at)}
                        </span>
                      </button>
                    </li>
                  ))}
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
