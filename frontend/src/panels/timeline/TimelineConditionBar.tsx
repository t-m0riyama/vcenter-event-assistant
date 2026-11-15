import { useState } from 'react'

import { ZonedRangeDetails } from '../../datetime/ZonedRangeDetails'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import type { useTimelineViewController } from '../../hooks/useTimelineViewController'
import { TIMELINE_ROLLING_PRESETS, type TimelineSourceKind } from '../../routing/timelineHash'
import { KIND_LABELS } from './timelineLabels'
import { anchorWindow } from './timelineModel'

type Controller = ReturnType<typeof useTimelineViewController>

const ANCHOR_WINDOWS = [
  { label: '起点の前後 15 分', halfWidthMs: 15 * 60_000 },
  { label: '起点の前後 1 時間', halfWidthMs: 3_600_000 },
  { label: '起点の前後 6 時間', halfWidthMs: 6 * 3_600_000 },
] as const

const SOURCE_OPTIONS: readonly TimelineSourceKind[] = ['event', 'alert']

/** 条件バー: 期間・起点・vCenter・対象・種別・更新。条件を変えると自動で読み込む。 */
export function TimelineConditionBar({ c }: { c: Controller }) {
  const { conditions, timeZone } = c
  const { range, anchor } = conditions
  // 入力中の文字列。Enter・フォーカスを外したときに確定する（途中の値で API を呼ばないため）
  const [minScoreDraft, setMinScoreDraft] = useState<string | null>(null)
  const minScoreInput = minScoreDraft ?? String(conditions.minScore)

  const commitMinScore = () => {
    if (minScoreDraft === null) return
    const n = Number(minScoreDraft)
    if (minScoreDraft.trim() !== '' && Number.isInteger(n) && n >= 0 && n <= 100 && n !== conditions.minScore) {
      c.setMinScore(n)
    }
    setMinScoreDraft(null)
  }

  const rangeLabel =
    range.mode === 'rolling'
      ? (TIMELINE_ROLLING_PRESETS.find((p) => p.durationMs === range.durationMs)?.label ?? '直近')
      : `${formatIsoInTimeZone(c.resolvedRange.from, timeZone)} ～ ${formatIsoInTimeZone(c.resolvedRange.to, timeZone)}`

  return (
    <section className="timeline-bar" aria-label="タイムラインの条件">
      <div className="timeline-bar__row" role="group" aria-label="期間のプリセット">
        {TIMELINE_ROLLING_PRESETS.map((p) => (
          <button
            key={p.key}
            type="button"
            className={`btn ${range.mode === 'rolling' && range.durationMs === p.durationMs ? 'btn--filled' : 'btn--gray'}`}
            aria-pressed={range.mode === 'rolling' && range.durationMs === p.durationMs}
            onClick={() => c.selectRollingPreset(p.durationMs)}
          >
            {p.label}
          </button>
        ))}
        {anchor ? (
          <>
            <span className="timeline-bar__sep" aria-hidden="true" />
            {ANCHOR_WINDOWS.map((w) => (
              <button
                key={w.label}
                type="button"
                className="btn btn--gray"
                onClick={() => c.setFixedRange(anchorWindow(anchor, w.halfWidthMs))}
              >
                {w.label}
              </button>
            ))}
          </>
        ) : null}
        <button
          type="button"
          className="btn btn--gray timeline-bar__refresh"
          onClick={c.refresh}
          aria-busy={c.loading ? 'true' : 'false'}
        >
          更新
        </button>
      </div>

      {anchor ? (
        <p className="timeline-bar__anchor">
          起点: <strong>{formatIsoInTimeZone(anchor, timeZone)}</strong>{' '}
          <button type="button" className="btn btn--gray" onClick={() => c.setAnchor(null)}>
            起点を解除
          </button>
        </p>
      ) : null}

      <ZonedRangeDetails
        displayLabel={rangeLabel}
        hint="開始と終了の両方を入力すると、その期間を固定して読み込みます。時刻は設定のタイムゾーンで入力します。"
        value={c.rangeParts}
        onChange={c.setRangeParts}
      />
      {c.rangeInputError ? (
        <p className="timeline-bar__field-error" role="alert">
          {c.rangeInputError}
        </p>
      ) : null}

      <div className="timeline-bar__filters">
        <label>
          vCenter
          <select value={conditions.vcenterId} onChange={(e) => c.setVcenterId(e.target.value)}>
            <option value="">全て</option>
            {c.vcenters.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label className="timeline-bar__entity">
          対象（ホスト・VM 名）
          <input
            type="search"
            value={c.entityInput}
            onChange={(e) => c.setEntityInput(e.target.value)}
            placeholder="部分一致"
            autoComplete="off"
          />
        </label>
        <fieldset className="timeline-bar__sources">
          <legend>種別</legend>
          {SOURCE_OPTIONS.map((kind) => (
            <label key={kind} className="timeline-bar__check">
              <input
                type="checkbox"
                checked={conditions.sources.includes(kind)}
                disabled={conditions.sources.length === 1 && conditions.sources.includes(kind)}
                onChange={() => c.toggleSource(kind)}
              />
              {KIND_LABELS[kind]}
            </label>
          ))}
        </fieldset>
      </div>

      <details className="toolbar__filters-details">
        <summary className="toolbar__filters-summary">
          <span className="toolbar__filters-summary__title">詳細設定</span>
          <span className="toolbar__filters-summary__preview">最小スコア {conditions.minScore}</span>
        </summary>
        <p className="hint toolbar__filters-hint">
          イベントはスコアがこの値以上のものだけを一覧に出します（俯瞰グラフの「その他のイベント」には含まれます）。
        </p>
        <label className="timeline-bar__min-score">
          最小スコア
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={100}
            step={1}
            className="toolbar__input--short"
            value={minScoreInput}
            onChange={(e) => setMinScoreDraft(e.target.value)}
            onBlur={commitMinScore}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitMinScore()
            }}
          />
        </label>
      </details>
    </section>
  )
}
