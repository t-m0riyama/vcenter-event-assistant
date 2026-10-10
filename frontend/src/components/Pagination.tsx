import { useRef } from 'react'

type PaginationProps = {
  total: number
  /** 表示中の先頭の件番号（1 始まり）。 */
  start: number
  /** 表示中の末尾の件番号。 */
  end: number
  canPrev: boolean
  canNext: boolean
  onPrev: () => void
  onNext: () => void
  loading?: boolean
  /** 一覧の上と下に置く。読み上げが 2 回にならないよう、件数の status は上だけに付ける。 */
  position: 'top' | 'bottom'
}

/** 一覧の前へ・次へと「全 N 件中 a–b 件を表示」。 */
export function Pagination({
  total,
  start,
  end,
  canPrev,
  canNext,
  onPrev,
  onNext,
  loading = false,
  position,
}: PaginationProps) {
  const navRef = useRef<HTMLElement>(null)
  /** 下で押したら、次のページの先頭が見えるようパネルの先頭へ戻す。 */
  const go = (handler: () => void) => () => {
    handler()
    if (position === 'bottom') {
      navRef.current?.closest('.panel')?.scrollIntoView?.({ block: 'start' })
    }
  }
  const meta = loading ? '読み込み中…' : total === 0 ? '全 0 件' : `全 ${total} 件中 ${start}–${end} 件を表示`
  return (
    <nav
      ref={navRef}
      className={`toolbar__pagination toolbar__pagination--${position}`}
      aria-label={position === 'top' ? 'ページ切り替え（上）' : 'ページ切り替え（下）'}
    >
      <button type="button" className="btn" disabled={!canPrev || loading} onClick={go(onPrev)}>
        前へ
      </button>
      <button type="button" className="btn" disabled={!canNext || loading} onClick={go(onNext)}>
        次へ
      </button>
      <span className="toolbar__meta" role={position === 'top' ? 'status' : undefined}>
        {meta}
      </span>
    </nav>
  )
}
